"""Orchestrator API — AI 驱动的多 Agent 编排入口

POST /api/v1/orchestrate          — 提交意图或结构化事件，启动编排
GET  /api/v1/orchestrate/{plan_id} — 查询执行计划历史（预留，暂返回 404）
"""

import asyncio
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/orchestrate", tags=["orchestrator"])


async def _get_db_with_tenant(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    """依赖：从 X-Tenant-ID header 提取租户 ID，返回带 RLS 隔离的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────────────────────


class OrchestrateRequest(BaseModel):
    """编排请求体

    intent 与 trigger_event 二选一（或同时提供，intent 优先）。
    """

    intent: Optional[str] = None  # 自然语言意图
    trigger_event: Optional[dict] = None  # 结构化 AgentEvent 数据
    context: dict = {}
    store_id: Optional[str] = None
    tenant_id: str = "default"  # 生产环境由 X-Tenant-ID header 注入


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("")
async def start_orchestration(
    req: OrchestrateRequest,
    x_tenant_id: str = Header(default="default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict[str, Any]:
    """提交意图或结构化事件，启动 AI 多 Agent 编排。

    返回 OrchestratorResult 序列化结果。
    编排完成后非阻塞写入 AgentDecisionLog 决策留痕。
    """
    from ..agents.event_bus import AgentEvent
    from ..agents.master import MasterAgent
    from ..services.decision_log_service import DecisionLogService

    # X-Tenant-ID header 优先；body 中的 tenant_id 作为向后兼容保留
    tenant_id = x_tenant_id if x_tenant_id != "default" else req.tenant_id

    if not req.intent and not req.trigger_event:
        raise HTTPException(
            status_code=422,
            detail="intent 或 trigger_event 至少提供一个",
        )

    master = MasterAgent(tenant_id=tenant_id, store_id=req.store_id)

    # 构建触发器：优先使用自然语言意图，否则重建 AgentEvent
    if req.intent:
        trigger: AgentEvent | str = req.intent
        trigger_summary = req.intent
    else:
        ev = req.trigger_event or {}
        trigger = AgentEvent(
            event_type=ev.get("event_type", "manual_trigger"),
            source_agent=ev.get("source_agent", "api"),
            store_id=req.store_id or ev.get("store_id", ""),
            data=ev.get("data", {}),
            tenant_id=tenant_id,
        )
        trigger_summary = f"{ev.get('event_type', 'manual_trigger')}"

    result = await master.orchestrate(trigger, req.context)

    logger.info(
        "orchestrate_api_completed",
        plan_id=result.plan_id,
        success=result.success,
        tenant_id=tenant_id,
    )

    # 非阻塞写入决策留痕（留痕失败不影响 API 响应）
    asyncio.create_task(
        DecisionLogService.log_orchestrator_result(
            db=db,
            tenant_id=tenant_id,
            store_id=req.store_id,
            plan_id=result.plan_id,
            trigger_summary=trigger_summary,
            plan_steps=result.plan_steps,
            orchestrator_result=result,
        )
    )

    return {
        "ok": True,
        "data": {
            "plan_id": result.plan_id,
            "success": result.success,
            "completed_steps": result.completed_steps,
            "failed_steps": result.failed_steps,
            "synthesis": result.synthesis,
            "recommended_actions": result.recommended_actions,
            "constraints_passed": result.constraints_passed,
            "confidence": result.confidence,
            "created_at": result.created_at.isoformat(),
        },
    }


@router.get("/skill-summary")
async def get_skill_summary() -> dict[str, Any]:
    """
    返回当前 Skill 注册状态摘要（不需要 X-Tenant-ID，元数据是全局的）。

    附加信息，不影响 AgentOrchestrator 核心编排逻辑。
    """
    from ..agents.skill_aware_orchestrator import SkillAwareOrchestrator

    summary = SkillAwareOrchestrator.get_ontology_summary()
    logger.info(
        "orchestrator_skill_summary_queried",
        total_skills=summary["total_skills"],
    )
    return {"ok": True, "data": summary}


@router.get("/{plan_id}")
async def get_plan_history(plan_id: str) -> dict[str, Any]:
    """查询执行计划历史（预留接口，待接入 AgentDecisionLog 持久化后实现）"""
    raise HTTPException(
        status_code=404,
        detail=f"plan_id={plan_id} 的历史记录查询功能尚未实现，敬请期待。",
    )
