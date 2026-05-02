"""金税四期合规 API 路由

Sprint B2: 全电发票 XML 校验 + 金税四期提交 + 发票 OCR 识别。

端点清单：
  POST /api/v1/finance/invoice/validate    — 校验发票 XML
  POST /api/v1/finance/invoice/submit      — 提交金税四期
  POST /api/v1/finance/invoice/ocr         — 发票 OCR 识别

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.invoice_compliance_service import (
    create_ocr_job,
    process_ocr_result,
    submit_to_golden_tax,
    validate_invoice_xml,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/finance/invoice",
    tags=["invoice-compliance"],
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


class ValidateRequest(BaseModel):
    invoice_id: str = Field(..., description="发票 ID")
    xml_content: str = Field(..., description="全电发票 XML 内容（金税四期格式）")
    schema_version: str = Field(default="1.0", description="XSD 版本号")


class SubmitRequest(BaseModel):
    invoice_id: str = Field(..., description="发票 ID")


class OCRRequest(BaseModel):
    image_path: str = Field(..., description="发票图片路径/URL")
    invoice_id: Optional[str] = Field(default=None, description="关联的发票 ID（可选）")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/validate")
async def validate_invoice(
    body: ValidateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """校验发票 XML 是否符合金税四期格式。

    检查:
    - schema 版本是否受支持
    - 是否包含所有必填字段（发票代码、号码、日期、购销方、金额等）

    校验通过 → status=validated
    校验失败 → status=rejected，返回具体错误列表
    """
    await _set_tenant(db, x_tenant_id)

    result = await validate_invoice_xml(
        db=db,
        tenant_id=x_tenant_id,
        invoice_id=body.invoice_id,
        xml_content=body.xml_content,
        schema_version=body.schema_version,
    )

    logger.info(
        "invoice_validate",
        invoice_id=body.invoice_id,
        ok=result.ok,
        error_count=len(result.errors),
    )

    return _ok({
        "invoice_id": body.invoice_id,
        "valid": result.ok,
        "errors": result.errors,
        "schema_version": result.schema_version,
    })


@router.post("/submit")
async def submit_invoice(
    body: SubmitRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """提交已校验的发票到金税四期。

    前置条件：发票 XML 必须已通过 validate 接口校验。
    当前为模拟提交，生产环境需接入诺诺全电等外部接口。

    返回 submission_id 作为提交凭证。
    """
    await _set_tenant(db, x_tenant_id)

    result = await submit_to_golden_tax(
        db=db,
        tenant_id=x_tenant_id,
        invoice_id=body.invoice_id,
    )

    if not result.ok:
        raise HTTPException(status_code=400, detail=result.message)

    logger.info(
        "invoice_submitted",
        invoice_id=body.invoice_id,
        submission_id=result.submission_id,
    )

    return _ok({
        "invoice_id": body.invoice_id,
        "submission_id": result.submission_id,
        "status": result.status,
        "message": result.message,
    })


@router.post("/ocr")
async def ocr_invoice(
    body: OCRRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """发票 OCR 识别（模拟接口）。

    创建 OCR 识别任务并返回识别结果。
    生产环境应接入腾讯云/阿里云/百度云等 OCR 服务。
    """
    await _set_tenant(db, x_tenant_id)

    # 创建 OCR 任务
    job_id = await create_ocr_job(
        db=db,
        tenant_id=x_tenant_id,
        image_path=body.image_path,
        invoice_id=body.invoice_id,
    )

    # 模拟处理 OCR 结果
    result = await process_ocr_result(
        db=db,
        tenant_id=x_tenant_id,
        job_id=job_id,
    )

    logger.info(
        "invoice_ocr_completed",
        job_id=job_id,
        invoice_id=body.invoice_id,
    )

    return _ok({
        "job_id": job_id,
        "invoice_id": body.invoice_id,
        "status": result["status"],
        "ocr_result": result.get("ocr_result"),
    })
