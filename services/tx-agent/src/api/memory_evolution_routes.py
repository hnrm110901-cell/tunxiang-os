"""记忆进化系统 API 路由 (Phase M1 — 记忆地基)

端点:
  # 长期语义记忆
  POST   /api/v1/agent/memory-evolution/remember              — 创建/更新记忆
  POST   /api/v1/agent/memory-evolution/recall                 — 检索记忆（混合搜索）
  GET    /api/v1/agent/memory-evolution/memories                — 列出记忆（分页+过滤）
  GET    /api/v1/agent/memory-evolution/memories/{id}           — 获取单条记忆
  DELETE /api/v1/agent/memory-evolution/memories/{id}           — 软删除记忆
  GET    /api/v1/agent/memory-evolution/store-profile/{store_id} — 门店画像
  GET    /api/v1/agent/memory-evolution/user-profile/{user_id}   — 用户画像

  # 情景记忆
  POST   /api/v1/agent/memory-evolution/episodes               — 记录情景
  GET    /api/v1/agent/memory-evolution/episodes                — 列出情景
  POST   /api/v1/agent/memory-evolution/episodes/search         — 搜索相似情景

  # 过程性记忆
  POST   /api/v1/agent/memory-evolution/procedures              — 学习规则
  GET    /api/v1/agent/memory-evolution/procedures               — 列出规则
  PATCH  /api/v1/agent/memory-evolution/procedures/{id}/outcome  — 更新成功率
  POST   /api/v1/agent/memory-evolution/procedures/match         — 匹配规则

  # 维护
  POST   /api/v1/agent/memory-evolution/maintenance/decay        — 触发衰减
  POST   /api/v1/agent/memory-evolution/maintenance/consolidate  — 触发整合
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.memory_evolution_service import MemoryEvolutionService

logger = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/agent/memory-evolution",
    tags=["memory-evolution"],
)


# ── Request / Response Models ──────────────────────────────────────────────


class RememberRequest(BaseModel):
    store_id: str | None = None
    user_id: str | None = None
    content: str = Field(..., min_length=1, max_length=2000)
    memory_type: str = Field(..., pattern="^(preference|pattern|knowledge|constraint)$")
    category: str = Field(..., min_length=1, max_length=100)
    agent_id: str = "chief"
    source_event: str | None = None
    importance: float = Field(default=0.5, ge=0, le=1)


class RecallRequest(BaseModel):
    store_id: str | None = None
    user_id: str | None = None
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)
    memory_types: list[str] | None = None
    categories: list[str] | None = None


class RecordEpisodeRequest(BaseModel):
    store_id: str
    episode_type: str = Field(..., pattern="^(anomaly|decision|incident|success)$")
    episode_date: str  # YYYY-MM-DD
    time_slot: str | None = None
    context: dict
    action_taken: dict | None = None
    outcome: dict | None = None
    lesson: str | None = None


class EpisodeSearchRequest(BaseModel):
    store_id: str | None = None
    query: str = Field(..., min_length=1, max_length=500)
    episode_types: list[str] | None = None
    top_k: int = Field(default=10, ge=1, le=50)


class LearnProcedureRequest(BaseModel):
    store_id: str | None = None
    procedure_name: str = Field(..., min_length=1, max_length=200)
    trigger_pattern: str = Field(..., min_length=1, max_length=500)
    trigger_config: dict
    action_template: dict


class ProcedureOutcomeRequest(BaseModel):
    success: bool


class ProcedureMatchRequest(BaseModel):
    store_id: str | None = None
    context: dict
    top_k: int = Field(default=5, ge=1, le=20)


# ── Dependency ─────────────────────────────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── Helper ─────────────────────────────────────────────────────────────────


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data}


def _fail(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"ok": False, "error": {"message": message}},
    )


# ── 长期语义记忆 ───────────────────────────────────────────────────────────


@router.post("/remember")
async def remember(
    req: RememberRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建或更新一条长期语义记忆"""
    svc = MemoryEvolutionService(db)
    memory = await svc.remember(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        user_id=req.user_id,
        content=req.content,
        memory_type=req.memory_type,
        category=req.category,
        agent_id=req.agent_id,
        source_event=req.source_event,
        importance=req.importance,
    )
    await db.commit()
    logger.info("memory.remembered", tenant_id=x_tenant_id, memory_id=str(memory.id), memory_type=req.memory_type)
    return _ok({"memory_id": str(memory.id)})


@router.post("/recall")
async def recall(
    req: RecallRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """检索记忆（混合搜索: 向量相似度 + 关键词 + 时间衰减）"""
    svc = MemoryEvolutionService(db)
    results = await svc.recall(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        user_id=req.user_id,
        query=req.query,
        top_k=req.top_k,
        memory_types=req.memory_types,
        categories=req.categories,
    )
    logger.info("memory.recalled", tenant_id=x_tenant_id, query_len=len(req.query), results_count=len(results))
    return _ok({"items": results, "total": len(results)})


@router.get("/memories")
async def list_memories(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: str | None = Query(default=None, description="按门店过滤"),
    user_id: str | None = Query(default=None, description="按用户过滤"),
    memory_type: str | None = Query(default=None, description="按类型过滤"),
    category: str | None = Query(default=None, description="按分类过滤"),
    agent_id: str | None = Query(default=None, description="按 Agent 过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """列出记忆（分页 + 过滤）"""
    svc = MemoryEvolutionService(db)
    items, total = await svc.list_memories(
        tenant_id=x_tenant_id,
        store_id=store_id,
        user_id=user_id,
        memory_type=memory_type,
        category=category,
        agent_id=agent_id,
        page=page,
        size=size,
    )
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/memories/{memory_id}")
async def get_memory(
    memory_id: UUID,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取单条记忆详情"""
    svc = MemoryEvolutionService(db)
    memory = await svc.get_memory(
        tenant_id=x_tenant_id,
        memory_id=str(memory_id),
    )
    if memory is None:
        _fail(404, f"记忆 {memory_id} 不存在")
    return _ok({"memory": memory})


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: UUID,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """软删除一条记忆"""
    svc = MemoryEvolutionService(db)
    deleted = await svc.delete_memory(
        tenant_id=x_tenant_id,
        memory_id=str(memory_id),
    )
    if not deleted:
        _fail(404, f"记忆 {memory_id} 不存在")
    await db.commit()
    logger.info("memory.deleted", tenant_id=x_tenant_id, memory_id=str(memory_id))
    return _ok({"deleted": str(memory_id)})


@router.get("/store-profile/{store_id}")
async def get_store_profile(
    store_id: str,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取门店记忆画像（聚合该门店的所有记忆维度）"""
    svc = MemoryEvolutionService(db)
    profile = await svc.get_store_profile(
        tenant_id=x_tenant_id,
        store_id=store_id,
    )
    return _ok({"profile": profile})


@router.get("/user-profile/{user_id}")
async def get_user_profile(
    user_id: str,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取用户记忆画像（聚合该用户的偏好/模式等记忆）"""
    svc = MemoryEvolutionService(db)
    profile = await svc.get_user_profile(
        tenant_id=x_tenant_id,
        user_id=user_id,
    )
    return _ok({"profile": profile})


# ── 情景记忆 ───────────────────────────────────────────────────────────────


@router.post("/episodes")
async def record_episode(
    req: RecordEpisodeRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """记录一个情景记忆（异常/决策/事件/成功案例）"""
    svc = MemoryEvolutionService(db)
    episode = await svc.record_episode(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        episode_type=req.episode_type,
        episode_date=req.episode_date,
        time_slot=req.time_slot,
        context=req.context,
        action_taken=req.action_taken,
        outcome=req.outcome,
        lesson=req.lesson,
    )
    await db.commit()
    logger.info("episode.recorded", tenant_id=x_tenant_id, episode_id=str(episode.id), episode_type=req.episode_type)
    return _ok({"episode_id": str(episode.id)})


@router.get("/episodes")
async def list_episodes(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: str | None = Query(default=None, description="按门店过滤"),
    episode_type: str | None = Query(default=None, description="按类型过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """列出情景记忆（分页 + 过滤）"""
    svc = MemoryEvolutionService(db)
    items, total = await svc.list_episodes(
        tenant_id=x_tenant_id,
        store_id=store_id,
        episode_type=episode_type,
        page=page,
        size=size,
    )
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/episodes/search")
async def search_episodes(
    req: EpisodeSearchRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """搜索相似情景（基于上下文相似度匹配历史情景）"""
    svc = MemoryEvolutionService(db)
    results = await svc.search_episodes(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        query=req.query,
        episode_types=req.episode_types,
        top_k=req.top_k,
    )
    return _ok({"items": results, "total": len(results)})


# ── 过程性记忆 ─────────────────────────────────────────────────────────────


@router.post("/procedures")
async def learn_procedure(
    req: LearnProcedureRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """学习一条过程性规则（if-then 模式）"""
    svc = MemoryEvolutionService(db)
    procedure = await svc.learn_procedure(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        procedure_name=req.procedure_name,
        trigger_pattern=req.trigger_pattern,
        trigger_config=req.trigger_config,
        action_template=req.action_template,
    )
    await db.commit()
    logger.info(
        "procedure.learned", tenant_id=x_tenant_id, procedure_id=str(procedure.id), procedure_name=req.procedure_name
    )
    return _ok({"procedure_id": str(procedure.id)})


@router.get("/procedures")
async def list_procedures(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: str | None = Query(default=None, description="按门店过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """列出过程性规则（分页 + 过滤）"""
    svc = MemoryEvolutionService(db)
    items, total = await svc.list_procedures(
        tenant_id=x_tenant_id,
        store_id=store_id,
        page=page,
        size=size,
    )
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.patch("/procedures/{procedure_id}/outcome")
async def update_procedure_outcome(
    procedure_id: UUID,
    req: ProcedureOutcomeRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新过程性规则的执行结果（用于计算成功率）"""
    svc = MemoryEvolutionService(db)
    updated = await svc.update_procedure_outcome(
        tenant_id=x_tenant_id,
        procedure_id=str(procedure_id),
        success=req.success,
    )
    if not updated:
        _fail(404, f"规则 {procedure_id} 不存在")
    await db.commit()
    logger.info("procedure.outcome_updated", tenant_id=x_tenant_id, procedure_id=str(procedure_id), success=req.success)
    return _ok({"procedure_id": str(procedure_id), "success": req.success})


@router.post("/procedures/match")
async def match_procedures(
    req: ProcedureMatchRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """根据当前上下文匹配适用的过程性规则"""
    svc = MemoryEvolutionService(db)
    results = await svc.match_procedures(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        context=req.context,
        top_k=req.top_k,
    )
    return _ok({"items": results, "total": len(results)})


# ── 维护 ───────────────────────────────────────────────────────────────────


@router.post("/maintenance/decay")
async def trigger_decay(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """手动触发记忆衰减（通常由 Worker 自动执行）"""
    svc = MemoryEvolutionService(db)
    decayed = await svc.decay_memories(tenant_id=x_tenant_id)
    await db.commit()
    logger.info("maintenance.decay_triggered", tenant_id=x_tenant_id, decayed=decayed)
    return _ok({"memories_decayed": decayed})


@router.post("/maintenance/consolidate")
async def trigger_consolidate(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """手动触发记忆整合（通常由 Worker 自动执行）"""
    svc = MemoryEvolutionService(db)
    consolidated = await svc.consolidate_memories(tenant_id=x_tenant_id)
    await db.commit()
    logger.info("maintenance.consolidate_triggered", tenant_id=x_tenant_id, consolidated=consolidated)
    return _ok({"memories_consolidated": consolidated})
