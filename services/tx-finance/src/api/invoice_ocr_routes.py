"""金税四期OCR发票识别 API 路由

# ROUTER REGISTRATION (在 tx-finance/src/main.py 中添加):
# from .api.invoice_ocr_routes import router as invoice_ocr_router
# app.include_router(invoice_ocr_router, prefix="/api/v1/invoice-ocr")

端点清单：
  POST  /invoice-ocr/recognize           单张OCR识别
  POST  /invoice-ocr/batch               批量OCR识别
  POST  /invoice-ocr/{result_id}/verify   发票验真
  GET   /invoice-ocr/results              查询OCR结果列表
  GET   /invoice-ocr/{result_id}          单条OCR结果详情
"""

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.invoice_ocr_service import (
    DuplicateInvoiceError,
    InvoiceOCRService,
    OCRProviderUnavailableError,
    OCRResultNotFoundError,
)

logger = structlog.get_logger()
router = APIRouter(tags=["invoice-ocr"])

_ocr_service = InvoiceOCRService()


# ── 依赖 ──────────────────────────────────────────────────────────────────────


async def _get_tenant_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_tenant_id(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID 格式无效",
        )


# ── Pydantic 请求/响应 Schema ─────────────────────────────────────────────────


class RecognizeRequest(BaseModel):
    image_url: str = Field(..., description="发票图片URL")
    provider: Optional[str] = Field(
        default=None,
        pattern="^(tencent|aliyun|baidu)$",
        description="指定OCR提供商(可选,默认按优先级降级)",
    )


class BatchRecognizeRequest(BaseModel):
    image_urls: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="发票图片URL列表(最多50张)",
    )


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


# ── 路由 ──────────────────────────────────────────────────────────────────────


@router.post("/recognize", status_code=status.HTTP_201_CREATED)
async def recognize_invoice(
    body: RecognizeRequest,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """单张发票OCR识别

    提交发票图片URL,调用OCR API识别发票内容。
    自动进行SHA-256去重检查。
    """
    try:
        result = await _ocr_service.recognize_invoice(
            db=db,
            tenant_id=tenant_id,
            image_url=body.image_url,
            provider=body.provider,
        )
    except OCRProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except DuplicateInvoiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return _ok(result)


@router.post("/batch", status_code=status.HTTP_201_CREATED)
async def batch_recognize(
    body: BatchRecognizeRequest,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """批量发票OCR识别

    提交多张发票图片URL,逐张识别。
    每张独立处理（不因单张失败而中断整批）。
    """
    results = await _ocr_service.batch_recognize(
        db=db,
        tenant_id=tenant_id,
        image_urls=body.image_urls,
    )

    success_count = sum(1 for r in results if r.get("ok"))
    return _ok({
        "results": results,
        "summary": {
            "total": len(body.image_urls),
            "success": success_count,
            "failed": len(body.image_urls) - success_count,
        },
    })


@router.post("/{result_id}/verify")
async def verify_invoice(
    result_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """发票验真

    调用税务局查验接口验证发票真伪（当前为模拟,预留真实接口）。
    """
    try:
        result = await _ocr_service.verify_invoice(
            db=db,
            tenant_id=tenant_id,
            ocr_result_id=result_id,
        )
    except OCRResultNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return _ok(result)


@router.get("/results")
async def list_ocr_results(
    page: int = Query(default=1, ge=1, description="页码"),
    size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        pattern="^(pending|verified|failed|duplicate)$",
        description="验真状态过滤",
    ),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """查询OCR结果列表

    支持分页和按验真状态过滤。
    """
    result = await _ocr_service.get_ocr_results(
        db=db,
        tenant_id=tenant_id,
        page=page,
        size=size,
        status_filter=status_filter,
    )
    return _ok(result)


@router.get("/{result_id}")
async def get_ocr_result_detail(
    result_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """查询单条OCR结果详情（含OCR原始JSON和验真结果）"""
    result = await _ocr_service.get_ocr_result_detail(
        db=db,
        tenant_id=tenant_id,
        result_id=result_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OCR结果 {result_id} 不存在",
        )
    return _ok(result)
