"""薪税申报 API 路由

端点列表（prefix /api/v1/tax-filing）：
  POST /generate                        — 生成申报数据预览
  POST /submit                          — 提交申报
  GET  /history                         — 申报历史
  GET  /{filing_id}                     — 申报详情
  GET  /annual-summary/{employee_id}    — 员工年度个税汇总
  POST /{filing_id}/retry               — 重试失败的申报
  GET  /stats                           — 统计（本年已申报月数/总税额/总人次）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.tax_filing_service import (
    check_filing_status,
    generate_tax_declaration,
    get_annual_summary,
    get_filing_history,
    get_filing_stats,
    retry_filing,
    submit_to_tax_bureau,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/tax-filing", tags=["tax-filing"])


# ── DB session 依赖 ──────────────────────────────────────────────────────────


async def get_db() -> AsyncSession:  # pragma: no cover
    """占位：运行时由 main.py lifespan 注入。"""
    raise NotImplementedError("请在 main.py 中覆盖 get_db 依赖")


# ── 请求模型 ─────────────────────────────────────────────────────────────────


class GenerateReq(BaseModel):
    month: str = Field(..., description="申报月份，格式 YYYY-MM", examples=["2026-04"])
    store_id: str = Field(..., description="门店 UUID")


class SubmitReq(BaseModel):
    declaration_id: str = Field(..., description="申报记录 UUID")


# ── 端点 ─────────────────────────────────────────────────────────────────────


@router.post("/generate")
async def api_generate(
    body: GenerateReq,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """生成个税申报数据预览"""
    try:
        data = await generate_tax_declaration(
            db=db,
            tenant_id=x_tenant_id,
            store_id=body.store_id,
            month=body.month,
        )
        await db.commit()
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/submit")
async def api_submit(
    body: SubmitReq,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """提交个税申报"""
    try:
        result = await submit_to_tax_bureau(
            db=db,
            tenant_id=x_tenant_id,
            declaration_id=body.declaration_id,
        )
        await db.commit()
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/history")
async def api_history(
    year: int | None = Query(None, ge=2020, le=2099, description="筛选年份"),
    store_id: str | None = Query(None, description="筛选门店"),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """申报历史记录"""
    items = await get_filing_history(
        db=db,
        tenant_id=x_tenant_id,
        store_id=store_id,
        year=year,
    )
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.get("/stats")
async def api_stats(
    year: int | None = Query(None, ge=2020, le=2099, description="统计年份"),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """统计：本年已申报月数/总税额/总人次"""
    data = await get_filing_stats(
        db=db,
        tenant_id=x_tenant_id,
        year=year,
    )
    return {"ok": True, "data": data}


@router.get("/annual-summary/{employee_id}")
async def api_annual_summary(
    employee_id: str,
    year: int = Query(..., ge=2020, le=2099, description="年度"),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """员工年度个税汇总"""
    try:
        data = await get_annual_summary(
            db=db,
            tenant_id=x_tenant_id,
            employee_id=employee_id,
            year=year,
        )
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{filing_id}")
async def api_detail(
    filing_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """申报详情"""
    try:
        data = await check_filing_status(
            db=db,
            tenant_id=x_tenant_id,
            declaration_id=filing_id,
        )
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{filing_id}/retry")
async def api_retry(
    filing_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """重试失败的申报"""
    try:
        result = await retry_filing(
            db=db,
            tenant_id=x_tenant_id,
            declaration_id=filing_id,
        )
        await db.commit()
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
