"""湘食通追溯上报 API 路由

Sprint B3: 湖南省湘食通食品安全追溯平台对接。

端点清单：
  POST /api/v1/civic/traceability/submit       — 提交追溯数据
  GET  /api/v1/civic/traceability/status/{submission_id} — 查询上报状态
  GET  /api/v1/civic/traceability/pending       — 查询待处理上报

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.trace_submission_service import (
    SUBMISSION_TYPES,
    get_pending_submissions,
    query_submission_status,
    submit_traceability,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/civic/traceability",
    tags=["civic-traceability"],
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    from sqlalchemy import text
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class SubmitTraceRequest(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    submission_type: str = Field(
        ...,
        description="上报类型",
    )
    payload: dict[str, Any] = Field(
        ...,
        description="上报数据（JSON 对象）",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/submit")
async def submit_traceability_data(
    body: SubmitTraceRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """提交追溯数据到湘食通平台。

    支持的上报类型：
    - ingredient_batch:   食材批次信息
    - waste_disposal:     废弃物处理
    - inspection_report:  检测报告

    当前为模拟提交，生产环境需接入湘食通官方 API。
    """
    await _set_tenant(db, x_tenant_id)

    # 校验上报类型
    if body.submission_type not in SUBMISSION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"不支持的上报类型: {body.submission_type}。"
                f"支持的类型: {', '.join(sorted(SUBMISSION_TYPES))}"
            ),
        )

    result = await submit_traceability(
        db=db,
        tenant_id=x_tenant_id,
        store_id=body.store_id,
        submission_type=body.submission_type,
        payload=body.payload,
    )

    if not result.ok:
        raise HTTPException(
            status_code=500,
            detail=result.message or "上报提交失败",
        )

    logger.info(
        "traceability_submitted",
        store_id=body.store_id,
        submission_type=body.submission_type,
        submission_id=result.submission_id,
    )

    return _ok({
        "id": result.id,
        "submission_id": result.submission_id,
        "submission_type": body.submission_type,
        "status": result.status,
        "message": result.message,
    })


@router.get("/status/{submission_id}")
async def get_submission_status(
    submission_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询湘食通平台上报状态。

    返回该条上报的完整记录，包括当前状态、提交时间和错误信息。
    """
    await _set_tenant(db, x_tenant_id)

    record = await query_submission_status(
        db=db,
        tenant_id=x_tenant_id,
        submission_id=submission_id,
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"上报记录 {submission_id} 不存在",
        )

    return _ok(record)


@router.get("/pending")
async def list_pending_submissions(
    store_id: Optional[str] = Query(None, description="按门店筛选"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询待处理的湘食通上报记录。

    返回所有状态为 draft 或 submitted 的记录，
    可按门店筛选，按创建时间倒序排列。
    """
    await _set_tenant(db, x_tenant_id)

    items = await get_pending_submissions(
        db=db,
        tenant_id=x_tenant_id,
        store_id=store_id,
    )

    return _ok({
        "items": items,
        "total": len(items),
    })
