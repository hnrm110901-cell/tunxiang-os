"""AI 结论可追溯证据链 API 路由 — Gap B-04

每条 AI 结论/推荐都必须可追溯到其数据来源。
本模块提供证据链的录入、查询和列表接口。

端点：
  POST /api/v1/analytics/evidence-chain            — 记录 AI 结论及其证据
  GET  /api/v1/analytics/evidence-chain/{chain_id} — 获取指定证据链
  GET  /api/v1/analytics/evidence-chain            — 列出最近 20 条（可按商户过滤）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["evidence-chain"])

# ── 数据模型 ──────────────────────────────────────────────────────────────────────

class EvidenceLink(BaseModel):
    source_type: str   # "event" | "materialized_view" | "db_query" | "merchant_target"
    source_ref: str    # 事件 ID / 物化视图名 / SQL 摘要 / 目标键
    value_summary: str # 人类可读摘要，例："revenue 日均 28,500元 (↑8%)"
    confidence: float  # 0.0-1.0


class AIEvidenceChainCreate(BaseModel):
    merchant_code: str
    conclusion_type: str    # "weekly_brief" | "daily_brief" | "anomaly" | "recommendation"
    conclusion_text: str
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    merchant_target_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AIEvidenceChain(BaseModel):
    chain_id: str
    merchant_code: str
    conclusion_type: str
    conclusion_text: str
    evidence_links: list[EvidenceLink]
    merchant_target_refs: list[str]
    confidence: float
    created_at: str


# ── 内存存储 ──────────────────────────────────────────────────────────────────────
# 最多保留 500 条，满时驱逐最旧的条目。
_MAX_CHAINS = 500
_chains: dict[str, AIEvidenceChain] = {}
_insertion_order: list[str] = []  # 维护插入顺序以便驱逐最旧条目


def _evict_if_full() -> None:
    """若存储已满，删除最旧的条目。"""
    while len(_chains) >= _MAX_CHAINS and _insertion_order:
        oldest_id = _insertion_order.pop(0)
        _chains.pop(oldest_id, None)


# ── 端点实现 ──────────────────────────────────────────────────────────────────────

@router.post("/evidence-chain", summary="记录 AI 结论证据链", status_code=201)
async def create_evidence_chain(payload: AIEvidenceChainCreate) -> dict:
    """录入一条 AI 结论及其可追溯的数据来源证据链。"""
    _evict_if_full()

    chain_id = str(uuid4())
    chain = AIEvidenceChain(
        chain_id=chain_id,
        merchant_code=payload.merchant_code,
        conclusion_type=payload.conclusion_type,
        conclusion_text=payload.conclusion_text,
        evidence_links=payload.evidence_links,
        merchant_target_refs=payload.merchant_target_refs,
        confidence=payload.confidence,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    _chains[chain_id] = chain
    _insertion_order.append(chain_id)

    logger.info(
        "evidence_chain_created",
        chain_id=chain_id,
        merchant_code=payload.merchant_code,
        conclusion_type=payload.conclusion_type,
        evidence_count=len(payload.evidence_links),
        confidence=payload.confidence,
    )

    return {
        "ok": True,
        "data": {
            "chain_id": chain_id,
            "message": "证据链已记录",
            "evidence_count": len(payload.evidence_links),
        },
    }


@router.get("/evidence-chain/{chain_id}", summary="获取指定证据链")
async def get_evidence_chain(chain_id: str) -> dict:
    """根据 chain_id 获取完整证据链详情。"""
    chain = _chains.get(chain_id)
    if chain is None:
        raise HTTPException(
            status_code=404,
            detail=f"证据链 {chain_id!r} 不存在",
        )
    return {"ok": True, "data": chain.model_dump()}


@router.get("/evidence-chain", summary="列出最近证据链（最多 20 条）")
async def list_evidence_chains(
    merchant_code: Optional[str] = None,
    conclusion_type: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """返回最近 N 条证据链，可按商户代码和结论类型过滤。"""
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit 范围：1-100")

    # 按 created_at 降序排列
    all_chains = sorted(
        _chains.values(),
        key=lambda c: c.created_at,
        reverse=True,
    )

    # 过滤
    if merchant_code:
        all_chains = [c for c in all_chains if c.merchant_code == merchant_code]
    if conclusion_type:
        all_chains = [c for c in all_chains if c.conclusion_type == conclusion_type]

    result = all_chains[:limit]

    return {
        "ok": True,
        "data": {
            "items": [c.model_dump() for c in result],
            "total": len(result),
            "filters": {
                "merchant_code": merchant_code,
                "conclusion_type": conclusion_type,
            },
        },
    }
