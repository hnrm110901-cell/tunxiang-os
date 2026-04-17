"""
证书 PDF 下载 / 二维码 / 公开验证 API — D11 培训证书 Nice-to-Have

端点：
  GET  /api/v1/hr/training/exam/certificates/{id}/pdf         # 需登录，下载证书 PDF
  GET  /api/v1/hr/training/exam/certificates/{id}/qrcode.png  # 需登录，返回二维码 PNG
  GET  /public/cert/verify/{cert_no}                          # 公开，无需登录，返回脱敏 JSON
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.dependencies import get_current_active_user
from ..models.employee import Employee
from ..models.training import ExamCertificate, TrainingCourse
from ..models.user import User
from ..services.certificate_pdf_service import (
    generate_certificate_pdf,
    load_certificate_pdf_from_disk,
    mask_holder_name,
)
from ..services.qrcode_service import generate_cert_qr

logger = structlog.get_logger()

# 需登录路由
router = APIRouter()

# 公开路由（不带 /api/v1 前缀，直接挂在根路径）
public_router = APIRouter()


# ── 需登录：PDF 下载 ──────────────────────────────────────────────


@router.get("/hr/training/exam/certificates/{cert_id}/pdf")
async def download_certificate_pdf(
    cert_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """下载证书 PDF。本人或管理员可下载。"""
    try:
        cert_uuid = uuid.UUID(cert_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="证书 ID 非法")

    res = await db.execute(select(ExamCertificate).where(ExamCertificate.id == cert_uuid))
    cert = res.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="证书不存在")

    # 简化鉴权：admin/hr/manager 全部可下载；否则仅本人
    role = (getattr(current_user, "role", "") or "").lower()
    user_emp_id = getattr(current_user, "employee_id", None) or getattr(current_user, "username", None)
    if role not in ("admin", "hr", "manager") and cert.employee_id != user_emp_id:
        raise HTTPException(status_code=403, detail="无权下载此证书")

    # 优先磁盘缓存
    pdf_bytes = load_certificate_pdf_from_disk(cert.cert_no)
    if not pdf_bytes:
        pdf_bytes = await generate_certificate_pdf(db, str(cert.id))
        await db.commit()

    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="证书 PDF 生成失败")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{cert.cert_no}.pdf"'},
    )


@router.get("/hr/training/exam/certificates/{cert_id}/qrcode.png")
async def certificate_qrcode(
    cert_id: str,
    size: int = 240,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """返回证书验证二维码 PNG。"""
    try:
        cert_uuid = uuid.UUID(cert_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="证书 ID 非法")

    res = await db.execute(select(ExamCertificate).where(ExamCertificate.id == cert_uuid))
    cert = res.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="证书不存在")

    size = max(120, min(int(size), 600))
    png = generate_cert_qr(cert.cert_no, size=size)
    if not png:
        raise HTTPException(status_code=500, detail="二维码生成失败")
    return Response(content=png, media_type="image/png")


# ── 公开：证书验证 ───────────────────────────────────────────────


@public_router.get("/public/cert/verify/{cert_no}")
async def public_verify_certificate(
    cert_no: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """公开证书验证端点（无需登录）。

    返回脱敏信息：
        {valid, holder_name_masked, course_name, cert_no,
         issued_at, expire_at, status, reason?}
    """
    res = await db.execute(select(ExamCertificate).where(ExamCertificate.cert_no == cert_no))
    cert = res.scalar_one_or_none()
    if not cert:
        return {
            "valid": False,
            "cert_no": cert_no,
            "reason": "not_found",
            "message": "未找到该证书",
        }

    # 课程
    course_res = await db.execute(select(TrainingCourse).where(TrainingCourse.id == cert.course_id))
    course = course_res.scalar_one_or_none()
    course_name = course.title if course else "未知课程"

    # 员工姓名脱敏
    emp_res = await db.execute(select(Employee).where(Employee.id == cert.employee_id))
    emp = emp_res.scalar_one_or_none()
    emp_name = getattr(emp, "name", None) or cert.employee_id
    masked = mask_holder_name(emp_name)

    # 有效性
    now = datetime.utcnow()
    expired = bool(cert.expire_at and cert.expire_at < now)
    revoked = cert.status == "revoked"
    valid = (not expired) and (not revoked) and cert.status == "active"

    reason = None
    if revoked:
        reason = "revoked"
    elif expired:
        reason = "expired"

    return {
        "valid": valid,
        "cert_no": cert.cert_no,
        "holder_name_masked": masked,
        "course_name": course_name,
        "issued_at": cert.issued_at.isoformat() if cert.issued_at else None,
        "expire_at": cert.expire_at.isoformat() if cert.expire_at else None,
        "status": cert.status,
        "reason": reason,
    }
