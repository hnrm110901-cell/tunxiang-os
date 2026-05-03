"""企微会话存档 + AI客诉识别 API — prefix /api/v1/growth/chat-archive

端点：
  1. GET  /permission        — 检查会话存档权限
  2. POST /fetch             — 拉取并分析会话数据
  3. GET  /complaints        — 客诉记录列表
  4. GET  /complaints/{id}   — 客诉详情
  5. PATCH /complaints/{id}  — 更新客诉处理状态
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..services.wecom_chat_archive_service import get_chat_archive_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/chat-archive", tags=["growth-chat-archive"])


# ─── 统一响应 ───


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ─── 请求模型 ───


class FetchRequest(BaseModel):
    seq: int = Field(default=0, ge=0, description="起始序列号")
    limit: int = Field(default=100, ge=1, le=1000, description="拉取条数")


class UpdateComplaintRequest(BaseModel):
    status: str = Field(..., description="处理状态: open/handling/resolved/closed")
    handler: Optional[str] = Field(default="", description="处理人")
    note: Optional[str] = Field(default="", description="处理备注")


# ─── 端点 ───


@router.get("/permission")
async def check_permission(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> dict:
    """检查会话存档权限。"""
    svc = get_chat_archive_service()
    try:
        result = await svc.check_permission()
        logger.info("chat_archive.permission_check", tenant_id=x_tenant_id, result=result)
        return ok_response(result)
    except Exception as exc:
        logger.error("chat_archive.permission_check_failed", tenant_id=x_tenant_id, error=str(exc))
        return error_response("ARCHIVE_API_ERROR", f"权限检查失败: {exc}")


@router.post("/fetch")
async def fetch_and_analyze(
    req: FetchRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """拉取加密会话数据并执行 AI 客诉分析。"""
    svc = get_chat_archive_service()
    try:
        result = await svc.fetch_and_analyze(seq=req.seq, limit=req.limit)
        logger.info(
            "chat_archive.fetch",
            tenant_id=x_tenant_id,
            seq=req.seq,
            total=result["total"],
            complaints=result["complaints_found"],
        )
        return ok_response(result)
    except Exception as exc:
        logger.error("chat_archive.fetch_failed", tenant_id=x_tenant_id, error=str(exc))
        return error_response("ARCHIVE_API_ERROR", f"拉取失败: {exc}")


@router.get("/complaints")
async def list_complaints(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """查询客诉记录列表。

    支持按 severity (P0/P1/P2/P3) 和 status (open/handling/resolved/closed) 过滤。
    """
    svc = get_chat_archive_service()
    try:
        results = svc.list_complaints(
            severity=severity,
            status=status,
            limit=limit,
        )
        return ok_response({"total": len(results), "items": results})
    except Exception as exc:
        logger.error("chat_archive.list_complaints_failed", error=str(exc))
        return error_response("ARCHIVE_ERROR", str(exc))


@router.get("/complaints/{complaint_id}")
async def get_complaint(
    complaint_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取客诉详情。"""
    svc = get_chat_archive_service()
    record = svc.get_complaint(complaint_id)
    if not record:
        raise HTTPException(status_code=404, detail="客诉记录不存在")
    return ok_response(record)


@router.patch("/complaints/{complaint_id}")
async def update_complaint(
    complaint_id: str,
    req: UpdateComplaintRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新客诉处理状态。"""
    valid_statuses = {"open", "handling", "resolved", "closed"}
    if req.status not in valid_statuses:
        return error_response("INVALID_STATUS", f"状态必须为 {valid_statuses}")

    svc = get_chat_archive_service()
    record = svc.update_complaint_status(
        complaint_id=complaint_id,
        status=req.status,
        handler=req.handler or "",
        note=req.note or "",
    )
    if not record:
        raise HTTPException(status_code=404, detail="客诉记录不存在")

    logger.info(
        "chat_archive.complaint_updated",
        complaint_id=complaint_id,
        status=req.status,
        handler=req.handler,
    )
    return ok_response(record)
