"""
AI 数智员工 API — 暴露 6 个数智员工的核心能力

路由聚合：
  /api/v1/ai-agents/interviewer/generate-questions
  /api/v1/ai-agents/interviewer/score
  /api/v1/ai-agents/auditor/scan
  /api/v1/ai-agents/performance-expert/analyze
（合同专员 / 排班专员 / 接待员 复用已有路由）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.ai_agent_market.audit_agent import AuditAgent
from ..services.ai_agent_market.interviewer_agent import InterviewerAgent
from ..services.ai_agent_market.performance_expert_agent import PerformanceExpertAgent

router = APIRouter(prefix="/api/v1/ai-agents", tags=["ai-agents"])

_interviewer = InterviewerAgent()
_performance_expert = PerformanceExpertAgent()


# ───────────────────── AI 面试官 ─────────────────────
class GenerateQuestionsRequest(BaseModel):
    job_title: str
    level: str = "junior"
    extra_requirements: Optional[str] = None


class ScoreRequest(BaseModel):
    answers: List[Dict[str, Any]]


@router.post("/interviewer/generate-questions")
async def interviewer_generate(body: GenerateQuestionsRequest):
    return await _interviewer.generate_questions(
        job_title=body.job_title,
        level=body.level,
        extra_requirements=body.extra_requirements,
    )


@router.post("/interviewer/score")
async def interviewer_score(body: ScoreRequest):
    return _interviewer.score_candidate(body.answers)


# ───────────────────── 执行审计员 ─────────────────────
class AuditScanRequest(BaseModel):
    tenant_id: str
    hours: int = Field(default=24, ge=1, le=168)


@router.post("/auditor/scan")
async def auditor_scan(body: AuditScanRequest, db: AsyncSession = Depends(get_db)):
    agent = AuditAgent(db)
    return await agent.scan(tenant_id=body.tenant_id, hours=body.hours)


# ───────────────────── 绩效专家 ─────────────────────
class PerformanceAnalyzeRequest(BaseModel):
    stores: List[Dict[str, Any]]
    peer_avg: Optional[Dict[str, float]] = None


@router.post("/performance-expert/analyze")
async def performance_analyze(body: PerformanceAnalyzeRequest):
    return await _performance_expert.analyze(
        stores=body.stores,
        peer_avg=body.peer_avg,
    )
