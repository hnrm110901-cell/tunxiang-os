"""AI 结论可追溯证据链 API 路由 — Gap B-04

每条 AI 结论/推荐都必须可追溯到其数据来源。
本模块提供证据链的录入、查询和列表接口。

端点：
  POST /api/v1/analytics/evidence-chain            — 记录 AI 结论及其证据
  GET  /api/v1/analytics/evidence-chain/{chain_id} — 获取指定证据链
  GET  /api/v1/analytics/evidence-chain            — 列出最近 20 条（可按商户过滤）
"""
from __future__ import annotations

import json
import uuid
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["evidence-chain"])

# ── 数据模型 ──────────────────────────────────────────────────────────────────────

class EvidenceLink(BaseModel):
    source_type: str   # "event" | "materialized_view" | "db_query" | "merchant_target"
    source_ref: str    # 事件 ID / 物化视图名 / SQL 摘要 / 目标键
    value_summary: str # 人类可读摘要，例："revenue 日均 28,500元 (↑8%)"
    confidence: float  # 0.0-1.0


class CreateEvidenceChainReq(BaseModel):
    merchant_code: str
    conclusion_type: str    # "weekly_brief" | "daily_brief" | "anomaly" | "recommendation"
    conclusion_text: str
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    merchant_target_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# Keep the old alias so existing callers still work
AIEvidenceChainCreate = CreateEvidenceChainReq


class AIEvidenceChain(BaseModel):
    chain_id: str
    merchant_code: str
    conclusion_type: str
    conclusion_text: str
    evidence_links: list[EvidenceLink]
    merchant_target_refs: list[str]
    confidence: float
    created_at: str


# ── 租户 UUID 推导 ────────────────────────────────────────────────────────────────

def _tenant_uuid(merchant_code: str) -> uuid.UUID:
    """将 merchant_code 映射到确定性 UUID（演示环境）。"""
    tenant_str = f"{merchant_code}-demo-tenant"
    return uuid.uuid5(uuid.NAMESPACE_DNS, tenant_str)


# ── 端点实现 ──────────────────────────────────────────────────────────────────────

@router.post("/evidence-chain", summary="记录 AI 结论证据链", status_code=201)
async def create_evidence_chain(payload: CreateEvidenceChainReq) -> dict:
    """录入一条 AI 结论及其可追溯的数据来源证据链。"""
    chain_id = str(uuid4())
    tenant_uuid = _tenant_uuid(payload.merchant_code)

    try:
        async with async_session_factory() as db:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_uuid)},
            )
            await db.execute(
                text("""
                    INSERT INTO ai_evidence_chains
                    (tenant_id, chain_id, merchant_code, conclusion_type, conclusion_text,
                     evidence_links, merchant_target_refs, confidence)
                    VALUES (:tid, :chain_id, :mc, :ctype, :ctext,
                            :elinks::jsonb, :trefs::jsonb, :conf)
                """),
                {
                    "tid": str(tenant_uuid),
                    "chain_id": chain_id,
                    "mc": payload.merchant_code,
                    "ctype": payload.conclusion_type,
                    "ctext": payload.conclusion_text,
                    "elinks": json.dumps(
                        [lnk.model_dump() for lnk in payload.evidence_links]
                    ),
                    "trefs": json.dumps(payload.merchant_target_refs),
                    "conf": str(payload.confidence),
                },
            )
            await db.commit()
    except SQLAlchemyError as exc:
        logger.error(
            "evidence_chain_db_insert_failed",
            chain_id=chain_id,
            merchant_code=payload.merchant_code,
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail="数据库写入失败，请稍后重试") from exc

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
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text("""
                    SELECT chain_id, merchant_code, conclusion_type, conclusion_text,
                           evidence_links, merchant_target_refs, confidence,
                           created_at
                    FROM ai_evidence_chains
                    WHERE chain_id = :chain_id
                    LIMIT 1
                """),
                {"chain_id": chain_id},
            )
            row = result.fetchone()
    except SQLAlchemyError as exc:
        logger.error(
            "evidence_chain_db_select_failed",
            chain_id=chain_id,
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail="数据库查询失败，请稍后重试") from exc

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"证据链 {chain_id!r} 不存在",
        )

    chain = AIEvidenceChain(
        chain_id=row.chain_id,
        merchant_code=row.merchant_code,
        conclusion_type=row.conclusion_type,
        conclusion_text=row.conclusion_text,
        evidence_links=[EvidenceLink(**lnk) for lnk in (row.evidence_links or [])],
        merchant_target_refs=list(row.merchant_target_refs or []),
        confidence=float(row.confidence),
        created_at=row.created_at.isoformat() if row.created_at else "",
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

    # Build dynamic WHERE clause
    conditions = []
    params: dict = {"limit": limit}

    if merchant_code:
        conditions.append("merchant_code = :merchant_code")
        params["merchant_code"] = merchant_code
    if conclusion_type:
        conditions.append("conclusion_type = :conclusion_type")
        params["conclusion_type"] = conclusion_type

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text(f"""
                    SELECT chain_id, merchant_code, conclusion_type, conclusion_text,
                           evidence_links, merchant_target_refs, confidence,
                           created_at
                    FROM ai_evidence_chains
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                params,
            )
            rows = result.fetchall()
    except SQLAlchemyError as exc:
        logger.error(
            "evidence_chain_db_list_failed",
            merchant_code=merchant_code,
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail="数据库查询失败，请稍后重试") from exc

    items = []
    for row in rows:
        chain = AIEvidenceChain(
            chain_id=row.chain_id,
            merchant_code=row.merchant_code,
            conclusion_type=row.conclusion_type,
            conclusion_text=row.conclusion_text,
            evidence_links=[EvidenceLink(**lnk) for lnk in (row.evidence_links or [])],
            merchant_target_refs=list(row.merchant_target_refs or []),
            confidence=float(row.confidence),
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        items.append(chain.model_dump())

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(items),
            "filters": {
                "merchant_code": merchant_code,
                "conclusion_type": conclusion_type,
            },
        },
    }
