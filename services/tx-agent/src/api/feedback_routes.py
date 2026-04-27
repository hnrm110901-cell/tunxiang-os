"""反馈信号与记忆进化 API 路由（Phase S4: 记忆进化闭环）

端点:
  POST   /api/v1/agent/feedback/signal               -- 记录信号
  GET    /api/v1/agent/feedback/signals/{store_id}    -- 列出信号
  POST   /api/v1/agent/feedback/analyze/{user_id}     -- 分析用户信号
  GET    /api/v1/agent/feedback/personalization        -- 获取个性化上下文
  POST   /api/v1/agent/feedback/evolve                -- 手动触发进化
  GET    /api/v1/agent/feedback/stats                  -- 进化统计
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.feedback_evolution_service import FeedbackEvolutionService

logger = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/agent/feedback",
    tags=["feedback"],
)


# ── Request Models ────────────────────────────────────────────────


class RecordSignalRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    user_id: str = Field(..., description="用户ID")
    signal_type: str = Field(
        ...,
        pattern="^(click|dismiss|dwell|feedback|override)$",
        description="信号类型",
    )
    source: str = Field(
        ...,
        pattern="^(im_card|dashboard|coaching|sop_task)$",
        description="信号来源",
    )
    source_id: str | None = Field(
        default=None,
        description="关联的卡片/任务/建议ID",
    )
    signal_data: dict = Field(
        default_factory=dict,
        description='信号详情，如 {"action": "expanded_cost_detail", "duration_sec": 45}',
    )


class AnalyzeRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=90, description="分析天数范围")


# ── Dependency ────────────────────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── Helper ────────────────────────────────────────────────────────


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data}


# ── 端点 ──────────────────────────────────────────────────────────


@router.post("/signal")
async def record_signal(
    req: RecordSignalRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """记录一个反馈信号（点击/关闭/停留/反馈/覆盖）"""
    svc = FeedbackEvolutionService(db)
    signal_id = await svc.record_signal(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        user_id=req.user_id,
        signal_type=req.signal_type,
        source=req.source,
        signal_data=req.signal_data,
        source_id=req.source_id,
    )
    await db.commit()
    logger.info(
        "feedback.signal_recorded",
        tenant_id=x_tenant_id,
        signal_id=signal_id,
        signal_type=req.signal_type,
    )
    return _ok({"signal_id": signal_id})


@router.get("/signals/{store_id}")
async def list_signals(
    store_id: str,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    user_id: str | None = Query(default=None, description="按用户过滤"),
    signal_type: str | None = Query(default=None, description="按信号类型过滤"),
    days: int = Query(default=7, ge=1, le=90, description="查询天数范围"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=100),
) -> dict:
    """列出指定门店的信号记录"""
    svc = FeedbackEvolutionService(db)
    result = await svc.list_signals(
        tenant_id=x_tenant_id,
        store_id=store_id,
        user_id=user_id,
        signal_type=signal_type,
        days=days,
        page=page,
        size=size,
    )
    return _ok(result)


@router.post("/analyze/{user_id}")
async def analyze_user_signals(
    user_id: str,
    req: AnalyzeRequest | None = None,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """分析用户近N天的信号模式，返回行为洞察"""
    days = req.days if req else 7
    svc = FeedbackEvolutionService(db)
    analysis = await svc.analyze_user_signals(
        tenant_id=x_tenant_id,
        user_id=user_id,
        days=days,
    )
    logger.info(
        "feedback.user_analyzed",
        tenant_id=x_tenant_id,
        user_id=user_id,
        days=days,
        total_signals=analysis.get("total_signals", 0),
    )
    return _ok(analysis)


@router.get("/personalization")
async def get_personalization(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: str = Query(..., description="门店ID"),
    user_id: str = Query(..., description="用户ID"),
) -> dict:
    """获取个性化上下文配置（供AI Coach使用）"""
    svc = FeedbackEvolutionService(db)
    context = await svc.get_personalization_context(
        tenant_id=x_tenant_id,
        store_id=store_id,
        user_id=user_id,
    )
    return _ok(context)


@router.post("/evolve")
async def trigger_evolve(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """手动触发记忆进化（通常由 Worker 每日自动执行）"""
    svc = FeedbackEvolutionService(db)
    result = await svc.evolve_memories(tenant_id=x_tenant_id)
    await db.commit()
    logger.info(
        "feedback.evolve_triggered",
        tenant_id=x_tenant_id,
        users_analyzed=result.get("users_analyzed", 0),
        memories_created=result.get("memories_created", 0),
        memories_updated=result.get("memories_updated", 0),
    )
    return _ok(result)


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取记忆进化统计概况"""
    svc = FeedbackEvolutionService(db)
    stats = await svc.get_evolution_stats(tenant_id=x_tenant_id)
    return _ok(stats)
