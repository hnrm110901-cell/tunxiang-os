"""
发票管理 API 路由
共7个端点，覆盖发票上传、OCR核验、金税验真、去重检查、科目修改、统计。

核心设计：
  - 上传即核验：POST /upload 触发完整核验流程（OCR+金税+去重+科目建议）
  - 核验结果填充供人确认，不自动驳回
  - 集团级去重跨品牌跨门店
"""
from __future__ import annotations

import uuid as uuid_lib
from datetime import date
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from src.api.expense_routes import get_current_user, get_tenant_id
from src.models.expense_enums import VerifyStatus
from src.services import invoice_verification_service

router = APIRouter()
log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schema
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceUploadMeta(BaseModel):
    """上传发票时的元数据（与文件一起提交）"""
    brand_id: UUID
    store_id: UUID
    application_id: Optional[UUID] = None      # 可先上传再关联申请
    expected_amount_fen: Optional[int] = None  # 预期金额（分），用于比对


class InvoiceCategoryUpdate(BaseModel):
    """人工确认科目"""
    confirmed_category_id: UUID
    notes: Optional[str] = None


class DuplicateCheckRequest(BaseModel):
    """集团去重检查（提交前预检）"""
    invoice_code: str
    invoice_number: str
    total_amount_fen: int  # 分


class BatchReverifyRequest(BaseModel):
    """批量重新核验"""
    invoice_ids: List[UUID] = Field(..., min_length=1, max_length=50)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

async def _upload_invoice_file(
    file_bytes: bytes,
    file_name: str,
    content_type: str,
) -> str:
    """
    上传发票文件到腾讯云 COS（invoices 目录），返回访问 URL。
    COS_SECRET_ID 未配置时自动进入 Mock 模式，返回本地伪路径。
    """
    from shared.integrations.cos_upload import get_cos_upload_service
    cos = get_cos_upload_service()
    result = await cos.upload_file(
        file_bytes=file_bytes,
        filename=file_name,
        content_type=content_type,
        folder="invoices",
    )
    return result["url"]


def _fen_to_yuan_str(fen: Optional[int]) -> Optional[str]:
    """将分转为元的字符串表示，例如 123456 → '1234.56'"""
    if fen is None:
        return None
    return f"{fen / 100:.2f}"


def _fake_invoice_warning() -> str:
    return "⚠️ 金税核验提示：发票真伪存疑，请人工复核后再审批"


# ─────────────────────────────────────────────────────────────────────────────
# 端点1：POST /upload — 上传发票并触发完整核验流程
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/upload", status_code=status.HTTP_201_CREATED, summary="上传发票并触发核验")
async def upload_invoice(
    file: UploadFile = File(..., description="发票图片（JPG/PNG/WebP）或PDF，最大10MB"),
    brand_id: UUID = Form(...),
    store_id: UUID = Form(...),
    application_id: Optional[UUID] = Form(None),
    expected_amount_fen: Optional[int] = Form(None),
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    上传发票文件并立即触发完整核验流程：
    OCR 结构化识别 → 金税四期验真 → 集团去重检查 → 科目自动建议。
    核验结果填充供人工确认，不自动驳回申请。
    """
    # 文件类型校验
    content_type = file.content_type or ""
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"不支持的文件类型：{content_type}。仅接受 JPG、PNG、WebP 图片或 PDF 文件。",
        )

    # 读取文件内容
    file_bytes = await file.read()

    # 文件大小校验
    if len(file_bytes) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件过大（{len(file_bytes) // 1024 // 1024:.1f}MB），最大允许10MB。",
        )

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传的文件内容为空，请重新选择文件。",
        )

    file_name = file.filename or "invoice.jpg"

    # 上传到腾讯云 COS（Mock 模式下返回本地伪路径）
    file_url = await _upload_invoice_file(file_bytes, file_name, content_type)

    log.info(
        "invoice_upload_request",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        file_name=file_name,
        file_size=len(file_bytes),
        content_type=content_type,
    )

    try:
        result = await invoice_verification_service.process_invoice_upload(
            db=db,
            tenant_id=tenant_id,
            brand_id=brand_id,
            store_id=store_id,
            uploader_id=current_user,
            file_bytes=file_bytes,
            file_name=file_name,
            file_type=content_type,
            file_url=file_url,
            file_size=len(file_bytes),
            application_id=application_id,
            expected_amount_fen=expected_amount_fen,
        )
    except Exception as exc:
        log.error("invoice_upload_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="发票上传处理失败，请稍后重试。",
        )

    # 补充金额双格式
    total_fen = result.get("total_amount_fen")
    result["total_amount_yuan"] = _fen_to_yuan_str(total_fen)

    # 真伪存疑时附加警告
    if result.get("verify_status") == VerifyStatus.VERIFIED_FAKE.value:
        result["warning"] = _fake_invoice_warning()

    return {"ok": True, "data": result}


# ─────────────────────────────────────────────────────────────────────────────
# 端点2：POST /{invoice_id}/verify — 手动触发金税核验
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{invoice_id}/verify", summary="手动触发金税核验")
async def verify_invoice(
    invoice_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    对已上传发票重新触发金税四期核验。
    适用场景：首次核验失败（接口超时/网络问题）后，接口恢复时手动重试。
    """
    # 查询发票信息
    try:
        result = await db.execute(
            text("""
                SELECT id, invoice_code, invoice_number, invoice_date,
                       total_amount, buyer_tax_id, verify_status
                FROM invoices
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": str(invoice_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().one_or_none()
    except Exception as exc:
        log.error("verify_invoice_query_error", invoice_id=str(invoice_id), error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="查询发票信息失败，请稍后重试。")

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不存在或无权访问。")

    invoice_date_str = ""
    if row.get("invoice_date"):
        try:
            invoice_date_str = row["invoice_date"].strftime("%Y-%m-%d")
        except AttributeError:
            invoice_date_str = str(row["invoice_date"])

    try:
        verify_result = await invoice_verification_service.verify_with_tax_authority(
            invoice_code=row.get("invoice_code") or "",
            invoice_number=row.get("invoice_number") or "",
            invoice_date=invoice_date_str,
            total_amount_fen=row.get("total_amount") or 0,
            buyer_tax_id=row.get("buyer_tax_id"),
        )
    except Exception as exc:
        log.error("verify_invoice_api_error", invoice_id=str(invoice_id), error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="金税核验接口调用失败，请稍后重试。")

    # 更新核验状态
    try:
        import json as _json
        await db.execute(
            text("""
                UPDATE invoices SET
                    verify_status = :status,
                    verify_response = :response,
                    updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": str(invoice_id),
                "tenant_id": str(tenant_id),
                "status": verify_result["status"],
                "response": _json.dumps(verify_result.get("raw_response", {}), ensure_ascii=False),
            },
        )
        await db.commit()
    except Exception as exc:
        log.error("verify_invoice_update_error", invoice_id=str(invoice_id), error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="核验状态更新失败，请稍后重试。")

    response_data = {
        "invoice_id": str(invoice_id),
        "verify_status": verify_result["status"],
        "message": verify_result.get("message", ""),
    }

    if verify_result["status"] == VerifyStatus.VERIFIED_FAKE.value:
        response_data["warning"] = _fake_invoice_warning()

    return {"ok": True, "data": response_data}


# ─────────────────────────────────────────────────────────────────────────────
# 端点3：GET /stats — 发票统计（注意：必须在 /{invoice_id} 之前注册，避免路由遮蔽）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats", summary="发票统计")
async def get_invoice_stats(
    store_id: Optional[UUID] = Query(None, description="按门店过滤"),
    date_from: Optional[date] = Query(None, description="统计起始日期（YYYY-MM-DD）"),
    date_to: Optional[date] = Query(None, description="统计截止日期（YYYY-MM-DD）"),
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    发票统计汇总：总数、各核验状态数量、重复发票数、总金额、OCR成功率。
    """
    conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
    params: dict = {"tenant_id": str(tenant_id)}

    if store_id is not None:
        conditions.append("store_id = :store_id")
        params["store_id"] = str(store_id)

    if date_from is not None:
        conditions.append("DATE(created_at) >= :date_from")
        params["date_from"] = date_from.isoformat()

    if date_to is not None:
        conditions.append("DATE(created_at) <= :date_to")
        params["date_to"] = date_to.isoformat()

    where_clause = " AND ".join(conditions)

    try:
        stats_result = await db.execute(
            text(f"""
                SELECT
                    COUNT(*)                                                        AS total_count,
                    COUNT(*) FILTER (WHERE verify_status = 'verified_real')        AS verified_real,
                    COUNT(*) FILTER (WHERE verify_status = 'verified_fake')        AS verified_fake,
                    COUNT(*) FILTER (WHERE verify_status = 'verify_failed')        AS verify_failed,
                    COUNT(*) FILTER (WHERE verify_status = 'skipped')              AS verify_skipped,
                    COUNT(*) FILTER (WHERE verify_status = 'pending')              AS verify_pending,
                    COUNT(*) FILTER (WHERE is_duplicate = TRUE)                    AS duplicate_count,
                    COALESCE(SUM(total_amount), 0)                                 AS total_amount_fen,
                    COUNT(*) FILTER (WHERE ocr_status = 'success')                 AS ocr_success_count,
                    COUNT(*) FILTER (WHERE ocr_status IN ('success', 'failed'))    AS ocr_attempted_count
                FROM invoices
                WHERE {where_clause}
            """),
            params,
        )
        row = stats_result.mappings().one()
    except Exception as exc:
        log.error("get_invoice_stats_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="统计查询失败，请稍后重试。")

    total_count = row["total_count"] or 0
    ocr_success_count = row["ocr_success_count"] or 0
    ocr_attempted_count = row["ocr_attempted_count"] or 0
    total_fen = int(row["total_amount_fen"] or 0)

    ocr_success_rate = (
        round(ocr_success_count / ocr_attempted_count, 4)
        if ocr_attempted_count > 0
        else 0.0
    )

    return {
        "ok": True,
        "data": {
            "total_count": total_count,
            "by_verify_status": {
                "verified_real": row["verified_real"] or 0,
                "verified_fake": row["verified_fake"] or 0,
                "verify_failed": row["verify_failed"] or 0,
                "skipped": row["verify_skipped"] or 0,
                "pending": row["verify_pending"] or 0,
            },
            "duplicate_count": row["duplicate_count"] or 0,
            "total_amount_fen": total_fen,
            "total_amount_yuan": _fen_to_yuan_str(total_fen),
            "ocr_success_rate": ocr_success_rate,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 端点4：POST /duplicate-check — 集团去重预检（必须在 /{invoice_id} 之前注册）
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/duplicate-check", summary="集团去重预检")
async def duplicate_check(
    body: DuplicateCheckRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    在正式上传前预检是否已有相同发票（跨品牌跨门店集团级查重）。
    前端在用户输入发票号码后可实时调用，及早提示重复风险。
    """
    dedup_hash = invoice_verification_service.compute_dedup_hash(
        invoice_code=body.invoice_code,
        invoice_number=body.invoice_number,
        total_amount_fen=body.total_amount_fen,
    )

    try:
        duplicate_info = await invoice_verification_service.check_duplicate(
            db=db,
            tenant_id=tenant_id,
            dedup_hash=dedup_hash,
        )
    except Exception as exc:
        log.error("duplicate_check_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="去重检查失败，请稍后重试。")

    is_duplicate = duplicate_info is not None
    return {
        "ok": True,
        "data": {
            "is_duplicate": is_duplicate,
            "duplicate_info": duplicate_info,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 端点5：GET / — 发票列表（分页）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", summary="发票列表")
async def list_invoices(
    store_id: Optional[UUID] = Query(None, description="按门店过滤"),
    application_id: Optional[UUID] = Query(None, description="按费用申请单过滤"),
    verify_status: Optional[str] = Query(None, description="核验状态过滤"),
    is_duplicate: Optional[bool] = Query(None, description="是否重复发票"),
    date_from: Optional[date] = Query(None, description="上传日期起（YYYY-MM-DD）"),
    date_to: Optional[date] = Query(None, description="上传日期止（YYYY-MM-DD）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    查询发票列表，支持多维度过滤，按上传时间倒序。
    返回分页结果，每条包含核验摘要信息。
    """
    conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
    params: dict = {"tenant_id": str(tenant_id)}

    if store_id is not None:
        conditions.append("store_id = :store_id")
        params["store_id"] = str(store_id)

    if application_id is not None:
        conditions.append("application_id = :application_id")
        params["application_id"] = str(application_id)

    if verify_status is not None:
        conditions.append("verify_status = :verify_status")
        params["verify_status"] = verify_status

    if is_duplicate is not None:
        conditions.append("is_duplicate = :is_duplicate")
        params["is_duplicate"] = is_duplicate

    if date_from is not None:
        conditions.append("DATE(created_at) >= :date_from")
        params["date_from"] = date_from.isoformat()

    if date_to is not None:
        conditions.append("DATE(created_at) <= :date_to")
        params["date_to"] = date_to.isoformat()

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM invoices WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar_one()

        rows_result = await db.execute(
            text(f"""
                SELECT id, store_id, application_id, file_name, file_url,
                       invoice_type, invoice_code, invoice_number, invoice_date,
                       seller_name, total_amount, tax_amount,
                       ocr_status, verify_status, is_duplicate,
                       suggested_category_id, confirmed_category_id,
                       needs_manual_review, created_at, updated_at
                FROM invoices
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = rows_result.mappings().all()
    except Exception as exc:
        log.error("list_invoices_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="查询发票列表失败，请稍后重试。")

    items = []
    for row in rows:
        total_fen = row.get("total_amount")
        item = {
            "id": str(row["id"]),
            "store_id": str(row["store_id"]) if row.get("store_id") else None,
            "application_id": str(row["application_id"]) if row.get("application_id") else None,
            "file_name": row.get("file_name"),
            "invoice_type": row.get("invoice_type"),
            "invoice_code": row.get("invoice_code"),
            "invoice_number": row.get("invoice_number"),
            "invoice_date": row["invoice_date"].isoformat() if row.get("invoice_date") else None,
            "seller_name": row.get("seller_name"),
            "total_amount_fen": total_fen,
            "total_amount_yuan": _fen_to_yuan_str(total_fen),
            "ocr_status": row.get("ocr_status"),
            "verify_status": row.get("verify_status"),
            "is_duplicate": row.get("is_duplicate", False),
            "needs_manual_review": row.get("needs_manual_review", False),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }
        if row.get("verify_status") == VerifyStatus.VERIFIED_FAKE.value:
            item["warning"] = _fake_invoice_warning()
        items.append(item)

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 端点4：GET /{invoice_id} — 发票详情
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{invoice_id}", summary="发票详情")
async def get_invoice(
    invoice_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取发票完整详情，包含 OCR 原始结果摘要、核验状态、科目建议。
    金额同时返回 _fen（分）和 _yuan（元字符串）两种格式。
    is_duplicate=True 时，响应中包含 duplicate_info（原始发票ID和上传信息）。
    """
    try:
        result = await db.execute(
            text("""
                SELECT id, tenant_id, brand_id, store_id, uploader_id,
                       application_id, file_name, file_type, file_url, file_size,
                       invoice_type, invoice_code, invoice_number, invoice_date,
                       seller_name, seller_tax_id, buyer_name, buyer_tax_id,
                       total_amount, tax_amount, amount_without_tax, tax_rate,
                       ocr_status, ocr_provider, ocr_confidence, ocr_raw,
                       verify_status, verify_response,
                       is_duplicate, duplicate_invoice_id, dedup_hash,
                       suggested_category_id, confirmed_category_id,
                       amount_deviation_fen, needs_manual_review,
                       compliance_issues, notes,
                       created_at, updated_at
                FROM invoices
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": str(invoice_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().one_or_none()
    except Exception as exc:
        log.error("get_invoice_error", invoice_id=str(invoice_id), error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="查询发票详情失败，请稍后重试。")

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不存在或无权访问。")

    total_fen = row.get("total_amount")
    tax_fen = row.get("tax_amount")
    amount_without_tax_fen = row.get("amount_without_tax")

    data = {
        "id": str(row["id"]),
        "brand_id": str(row["brand_id"]) if row.get("brand_id") else None,
        "store_id": str(row["store_id"]) if row.get("store_id") else None,
        "uploader_id": str(row["uploader_id"]) if row.get("uploader_id") else None,
        "application_id": str(row["application_id"]) if row.get("application_id") else None,
        "file_name": row.get("file_name"),
        "file_type": row.get("file_type"),
        "file_url": row.get("file_url"),
        "file_size": row.get("file_size"),
        "invoice_type": row.get("invoice_type"),
        "invoice_code": row.get("invoice_code"),
        "invoice_number": row.get("invoice_number"),
        "invoice_date": row["invoice_date"].isoformat() if row.get("invoice_date") else None,
        "seller_name": row.get("seller_name"),
        "seller_tax_id": row.get("seller_tax_id"),
        "buyer_name": row.get("buyer_name"),
        "buyer_tax_id": row.get("buyer_tax_id"),
        "total_amount_fen": total_fen,
        "total_amount_yuan": _fen_to_yuan_str(total_fen),
        "tax_amount_fen": tax_fen,
        "tax_amount_yuan": _fen_to_yuan_str(tax_fen),
        "amount_without_tax_fen": amount_without_tax_fen,
        "amount_without_tax_yuan": _fen_to_yuan_str(amount_without_tax_fen),
        "tax_rate": row.get("tax_rate"),
        "ocr_status": row.get("ocr_status"),
        "ocr_provider": row.get("ocr_provider"),
        "ocr_confidence": row.get("ocr_confidence"),
        "ocr_raw_summary": _ocr_raw_summary(row.get("ocr_raw")),
        "verify_status": row.get("verify_status"),
        "is_duplicate": row.get("is_duplicate", False),
        "suggested_category_id": str(row["suggested_category_id"]) if row.get("suggested_category_id") else None,
        "confirmed_category_id": str(row["confirmed_category_id"]) if row.get("confirmed_category_id") else None,
        "amount_deviation_fen": row.get("amount_deviation_fen"),
        "needs_manual_review": row.get("needs_manual_review", False),
        "compliance_issues": row.get("compliance_issues"),
        "notes": row.get("notes"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }

    # 重复发票时附加原始发票信息
    if row.get("is_duplicate") and row.get("duplicate_invoice_id"):
        duplicate_id = row["duplicate_invoice_id"]
        try:
            dup_result = await db.execute(
                text("""
                    SELECT id, store_id, file_name, created_at
                    FROM invoices
                    WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
                """),
                {"id": str(duplicate_id), "tenant_id": str(tenant_id)},
            )
            dup_row = dup_result.mappings().one_or_none()
        except Exception as exc:
            log.warning("get_invoice_dup_query_error", error=str(exc))
            dup_row = None

        data["duplicate_info"] = {
            "duplicate_invoice_id": str(duplicate_id),
            "store_id": str(dup_row["store_id"]) if dup_row and dup_row.get("store_id") else None,
            "file_name": dup_row.get("file_name") if dup_row else None,
            "uploaded_at": dup_row["created_at"].isoformat() if dup_row and dup_row.get("created_at") else None,
        }

    if row.get("verify_status") == VerifyStatus.VERIFIED_FAKE.value:
        data["warning"] = _fake_invoice_warning()

    return {"ok": True, "data": data}


def _ocr_raw_summary(ocr_raw) -> Optional[dict]:
    """从 OCR 原始结果中提取摘要信息（避免暴露完整大 JSON）。"""
    if not ocr_raw:
        return None
    if isinstance(ocr_raw, str):
        import json as _json
        try:
            ocr_raw = _json.loads(ocr_raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(ocr_raw, dict):
        return None
    return {
        "provider": ocr_raw.get("provider"),
        "confidence": ocr_raw.get("confidence"),
        "invoice_type": ocr_raw.get("invoice_type"),
        "items_count": len(ocr_raw.get("items", [])),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 端点6：PATCH /{invoice_id}/category — 人工确认科目
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{invoice_id}/category", summary="人工确认科目")
async def update_invoice_category(
    invoice_id: UUID,
    body: InvoiceCategoryUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    人工确认发票科目分类。
    同时如果该发票已关联 expense_item，则同步更新 expense_item.category_id。
    """
    # 查询发票（校验归属 + 获取 application_id）
    try:
        result = await db.execute(
            text("""
                SELECT id, application_id
                FROM invoices
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": str(invoice_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().one_or_none()
    except Exception as exc:
        log.error("update_category_query_error", invoice_id=str(invoice_id), error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="查询发票失败，请稍后重试。")

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不存在或无权访问。")

    # 更新发票 confirmed_category_id
    try:
        await db.execute(
            text("""
                UPDATE invoices SET
                    confirmed_category_id = :category_id,
                    notes = COALESCE(:notes, notes),
                    updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": str(invoice_id),
                "tenant_id": str(tenant_id),
                "category_id": str(body.confirmed_category_id),
                "notes": body.notes,
            },
        )
    except Exception as exc:
        log.error("update_category_update_error", invoice_id=str(invoice_id), error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新科目失败，请稍后重试。")

    # 同步更新关联的 expense_item（如果有）
    application_id = row.get("application_id")
    if application_id:
        try:
            await db.execute(
                text("""
                    UPDATE expense_items SET
                        category_id = :category_id,
                        updated_at = NOW()
                    WHERE application_id = :application_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                """),
                {
                    "application_id": str(application_id),
                    "tenant_id": str(tenant_id),
                    "category_id": str(body.confirmed_category_id),
                },
            )
        except Exception as exc:
            # expense_item 更新失败不阻断主流程，仅记录日志
            log.warning(
                "update_category_expense_item_error",
                invoice_id=str(invoice_id),
                application_id=str(application_id),
                error=str(exc),
            )

    await db.commit()

    # 返回更新后的发票
    try:
        updated_result = await db.execute(
            text("""
                SELECT id, invoice_code, invoice_number, invoice_type,
                       seller_name, total_amount, verify_status,
                       suggested_category_id, confirmed_category_id, notes,
                       updated_at
                FROM invoices
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": str(invoice_id), "tenant_id": str(tenant_id)},
        )
        updated_row = updated_result.mappings().one_or_none()
    except Exception as exc:
        log.warning("update_category_fetch_updated_error", error=str(exc))
        updated_row = None

    if updated_row:
        total_fen = updated_row.get("total_amount")
        data = {
            "id": str(updated_row["id"]),
            "invoice_code": updated_row.get("invoice_code"),
            "invoice_number": updated_row.get("invoice_number"),
            "invoice_type": updated_row.get("invoice_type"),
            "seller_name": updated_row.get("seller_name"),
            "total_amount_fen": total_fen,
            "total_amount_yuan": _fen_to_yuan_str(total_fen),
            "verify_status": updated_row.get("verify_status"),
            "suggested_category_id": str(updated_row["suggested_category_id"]) if updated_row.get("suggested_category_id") else None,
            "confirmed_category_id": str(updated_row["confirmed_category_id"]) if updated_row.get("confirmed_category_id") else None,
            "notes": updated_row.get("notes"),
            "updated_at": updated_row["updated_at"].isoformat() if updated_row.get("updated_at") else None,
        }
    else:
        data = {"id": str(invoice_id), "confirmed_category_id": str(body.confirmed_category_id)}

    return {"ok": True, "data": data}
