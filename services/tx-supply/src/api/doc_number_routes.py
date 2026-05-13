"""doc_number_routes — 业务单号定制规则配置 + 生成 API（PRD-03 / Tier 1）

接口列表（CLAUDE.md §10 RESTful 规范）：
  POST   /api/v1/supply/doc-number/generate     生成单号（业务调用）
  GET    /api/v1/supply/doc-number-rules         列出 tenant 规则（含系统默认 fallback）
  POST   /api/v1/supply/doc-number-rules         配置 tenant 规则（覆盖系统默认）
  DELETE /api/v1/supply/doc-number-rules/{type}  撤销 tenant 规则（回到系统默认）
"""

from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..services.doc_number_service import (
    SYSTEM_TENANT_ID,
    DocNumberError,
    generate,
    upsert_rule,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["doc-number"],
)


# ─── 请求/响应模型 ──────────────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    doc_type: str = Field(..., description="单据类型，如 purchase_order")
    store_id: Optional[str] = Field(None, description="门店 UUID（store scope 必填）")
    store_code: Optional[str] = Field(None, description="门店编码（模板含 {store_code} 必填）")


class GenerateResponse(BaseModel):
    ok: bool
    data: dict


class UpsertRuleRequest(BaseModel):
    doc_type: str
    template: str
    seq_scope: str = Field(..., description="global / daily / monthly / store")
    description: Optional[str] = None


class RuleOut(BaseModel):
    tenant_id: str
    doc_type: str
    template: str
    seq_scope: str
    is_active: bool
    is_system_default: bool


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.post("/doc-number/generate", response_model=GenerateResponse)
async def generate_doc_number(
    payload: GenerateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """生成单号 — 内部 service 间也走本接口，避免重复实现 advisory_lock。"""
    try:
        doc_number = await generate(
            db,
            tenant_id=x_tenant_id,
            doc_type=payload.doc_type,
            store_id=payload.store_id,
            store_code=payload.store_code,
        )
        await db.commit()
    except DocNumberError as e:
        await db.rollback()
        logger.warning(
            "doc_number_generate_failed",
            tenant_id=x_tenant_id,
            doc_type=payload.doc_type,
            error=str(e),
        )
        raise HTTPException(status_code=422, detail={"code": "DOC_NUMBER_INVALID", "reason": str(e)})

    return {"ok": True, "data": {"doc_number": doc_number, "doc_type": payload.doc_type}}


@router.get("/doc-number-rules")
async def list_rules(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出对本 tenant 有效的规则（tenant 自定义 + 系统默认 union）。

    tenant 自定义优先于系统默认（同 doc_type 只显示 tenant 行）。
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(x_tenant_id)},
    )
    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT ON (doc_type)
                       tenant_id::text AS tenant_id,
                       doc_type, template, seq_scope, is_active,
                       (tenant_id = :sys::uuid) AS is_system_default
                FROM doc_number_rules
                WHERE is_active = TRUE
                  AND (tenant_id::text = :tid OR tenant_id = :sys::uuid)
                ORDER BY doc_type, (tenant_id::text = :tid) DESC
                """
            ),
            {"tid": str(x_tenant_id), "sys": SYSTEM_TENANT_ID},
        )
    ).mappings().all()

    items: List[dict] = [
        {
            "tenant_id": r["tenant_id"],
            "doc_type": r["doc_type"],
            "template": r["template"],
            "seq_scope": r["seq_scope"],
            "is_active": bool(r["is_active"]),
            "is_system_default": bool(r["is_system_default"]),
        }
        for r in rows
    ]
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.post("/doc-number-rules")
async def configure_rule(
    payload: UpsertRuleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """配置 tenant 自定义规则（覆盖系统默认）。模板坏 → 422。"""
    try:
        rule = await upsert_rule(
            db,
            tenant_id=x_tenant_id,
            doc_type=payload.doc_type,
            template=payload.template,
            seq_scope=payload.seq_scope,
            description=payload.description,
            created_by=x_user_id,
        )
        await db.commit()
    except DocNumberError as e:
        await db.rollback()
        raise HTTPException(status_code=422, detail={"code": "DOC_NUMBER_INVALID", "reason": str(e)})

    logger.info(
        "doc_number_rule_upserted",
        tenant_id=x_tenant_id,
        doc_type=payload.doc_type,
        template=payload.template,
        scope=payload.seq_scope,
    )
    return {
        "ok": True,
        "data": {
            "tenant_id": rule.tenant_id,
            "doc_type": rule.doc_type,
            "template": rule.template,
            "seq_scope": rule.seq_scope,
            "is_active": rule.is_active,
        },
    }


@router.delete("/doc-number-rules/{doc_type}")
async def revoke_rule(
    doc_type: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """撤销 tenant 规则（回到系统默认）。系统默认行受 RLS WITH CHECK 保护不可删。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(x_tenant_id)},
    )
    result = await db.execute(
        text(
            """
            DELETE FROM doc_number_rules
            WHERE tenant_id::text = :tid AND doc_type = :doc_type
            """
        ),
        {"tid": str(x_tenant_id), "doc_type": doc_type},
    )
    await db.commit()
    return {"ok": True, "data": {"deleted": result.rowcount}}
