"""
文件上传 API 路由

端点:
  POST   /api/v1/upload/image   — 图片上传（限 10MB，jpg/png/webp/gif）
  POST   /api/v1/upload/file    — 通用文件上传（限 50MB）
  POST   /api/v1/upload/base64  — Base64 上传
  DELETE /api/v1/upload/{key:path} — 删除文件

所有端点需要 X-Tenant-ID header（由 TenantMiddleware 校验）。
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from shared.integrations.cos_upload import (
    ALL_ALLOWED_TYPES,
    IMAGE_TYPES,
    COSUploadError,
    get_cos_upload_service,
)

from ..response import ok

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/upload", tags=["upload"])

# ─── 请求/响应模型 ───


class Base64UploadRequest(BaseModel):
    data: str = Field(..., description="Base64 编码数据（可带 data:xxx;base64, 前缀）")
    filename: str = Field(..., max_length=255, description="文件名")
    folder: str = Field(default="general", description="存储目录")
    content_type: str = Field(default="image/png", description="MIME 类型")


class UploadResponse(BaseModel):
    url: str
    key: str
    size: int


# ─── 图片上传 ───


@router.post("/image", summary="图片上传", response_model=dict)
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    folder: str = Form(default="general"),
):
    """上传图片文件（jpg/png/webp/gif），单文件限 10MB"""
    cos = get_cos_upload_service()

    content_type = file.content_type or "application/octet-stream"
    if content_type not in IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持图片格式: {', '.join(sorted(IMAGE_TYPES))}，收到: {content_type}",
        )

    file_bytes = await file.read()

    try:
        result = await cos.upload_file(
            file_bytes=file_bytes,
            filename=file.filename or "image",
            content_type=content_type,
            folder=folder,
        )
    except COSUploadError as exc:
        logger.warning("upload_image_failed", error=str(exc), folder=folder)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "upload_image_success",
        key=result["key"],
        size=result["size"],
        folder=folder,
        tenant_id=getattr(request.state, "tenant_id", None),
    )
    return ok(result)


# ─── 通用文件上传 ───


@router.post("/file", summary="通用文件上传", response_model=dict)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    folder: str = Form(default="general"),
):
    """上传通用文件（图片/文档/视频/音频），单文件限 50MB"""
    cos = get_cos_upload_service()

    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALL_ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {content_type}",
        )

    file_bytes = await file.read()

    try:
        result = await cos.upload_file(
            file_bytes=file_bytes,
            filename=file.filename or "file",
            content_type=content_type,
            folder=folder,
        )
    except COSUploadError as exc:
        logger.warning("upload_file_failed", error=str(exc), folder=folder)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "upload_file_success",
        key=result["key"],
        size=result["size"],
        folder=folder,
        tenant_id=getattr(request.state, "tenant_id", None),
    )
    return ok(result)


# ─── Base64 上传 ───


@router.post("/base64", summary="Base64 上传", response_model=dict)
async def upload_base64(
    request: Request,
    body: Base64UploadRequest,
):
    """上传 Base64 编码文件"""
    cos = get_cos_upload_service()

    try:
        result = await cos.upload_base64(
            base64_data=body.data,
            filename=body.filename,
            folder=body.folder,
            content_type=body.content_type,
        )
    except COSUploadError as exc:
        logger.warning("upload_base64_failed", error=str(exc), folder=body.folder)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "upload_base64_success",
        key=result["key"],
        size=result["size"],
        folder=body.folder,
        tenant_id=getattr(request.state, "tenant_id", None),
    )
    return ok(result)


# ─── 删除文件 ───


@router.delete("/{key:path}", summary="删除文件", response_model=dict)
async def delete_file(
    request: Request,
    key: str,
):
    """根据 key 删除已上传的文件"""
    cos = get_cos_upload_service()

    if not key or len(key) < 5:
        raise HTTPException(status_code=400, detail="无效的文件 key")

    success = await cos.delete_file(key)

    if not success:
        raise HTTPException(status_code=500, detail="文件删除失败")

    logger.info(
        "upload_delete_success",
        key=key,
        tenant_id=getattr(request.state, "tenant_id", None),
    )
    return ok({"key": key, "deleted": True})
