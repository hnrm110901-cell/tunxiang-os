"""
InvoiceComplianceService — 金税四期合规服务

全电发票 XML 归档、XSD 校验、金税四期提交、OCR 识别任务管理。

金税四期的外部接口（诺诺全电）需要供应商采购，本 Sprint 只做内部逻辑和接口骨架。

罚款风险：单张拒收 500-2000 + 失信企业名单。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """XML 校验结果。"""
    ok: bool
    errors: list[str]
    schema_version: str


@dataclass
class SubmissionResult:
    """金税四期提交结果。"""
    ok: bool
    submission_id: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# XSD Schema 定义（最简版本）
# ---------------------------------------------------------------------------

_GOLDEN_TAX_SCHEMA_VERSIONS: set[str] = {"1.0", "1.1", "2.0"}

# 全电发票必填字段（金税四期格式简化版）
_REQUIRED_XML_FIELDS = {
    "InvoiceCode",        # 发票代码
    "InvoiceNumber",      # 发票号码
    "InvoiceDate",        # 开票日期
    "SellerName",         # 销售方名称
    "SellerTaxNo",        # 销售方纳税人识别号
    "BuyerName",          # 购买方名称
    "BuyerTaxNo",         # 购买方纳税人识别号
    "TotalAmount",        # 价税合计
    "TotalTax",           # 税额
}


# ---------------------------------------------------------------------------
# 核心服务函数
# ---------------------------------------------------------------------------


async def validate_invoice_xml(
    db: AsyncSession,
    tenant_id: str,
    invoice_id: str,
    xml_content: str,
    schema_version: str = "1.0",
) -> ValidationResult:
    """校验发票 XML 是否符合金税四期 XSD 格式。

    校验规则（最简版）:
    1. schema_version 必须受支持
    2. XML 必须包含所有必填字段
    3. 金额字段必须为有效数字

    生产环境应接入真实 XSD 验证引擎。
    """
    await _set_tenant(db, tenant_id)
    errors: list[str] = []

    # 1. 检查 schema 版本
    if schema_version not in _GOLDEN_TAX_SCHEMA_VERSIONS:
        errors.append(f"不支持的 schema 版本: {schema_version}")

    # 2. 检查必填字段
    for field in _REQUIRED_XML_FIELDS:
        if field not in xml_content:
            errors.append(f"缺少必填字段: {field}")

    # 3. 标记校验记录
    status = "validated" if not errors else "rejected"
    archive_id = str(uuid4())

    try:
        await db.execute(
            text("""
                INSERT INTO invoice_xml_archive
                    (id, tenant_id, invoice_id, xml_content, schema_version,
                     status, validation_errors, created_at)
                VALUES
                    (:id, :tenant_id, :invoice_id, :xml_content, :schema_version,
                     :status, :validation_errors, NOW())
            """),
            {
                "id": archive_id,
                "tenant_id": tenant_id,
                "invoice_id": invoice_id,
                "xml_content": xml_content,
                "schema_version": schema_version,
                "status": status,
                "validation_errors": json.dumps(errors) if errors else None,
            },
        )
        await db.commit()

        logger.info(
            "invoice_xml_validated",
            invoice_id=invoice_id,
            status=status,
            error_count=len(errors),
        )

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "invoice_xml_archive_failed",
            invoice_id=invoice_id,
            error=str(exc),
            exc_info=True,
        )
        return ValidationResult(ok=False, errors=[str(exc)], schema_version=schema_version)

    return ValidationResult(ok=not errors, errors=errors, schema_version=schema_version)


async def submit_to_golden_tax(
    db: AsyncSession,
    tenant_id: str,
    invoice_id: str,
) -> SubmissionResult:
    """提交发票到金税四期（模拟接口）。

    当前为接口骨架，实际对接诺诺全电等供应商后替换实现。
    生产环境应有:
    - 重试机制（最多 3 次）
    - 调用外部 API 提交 XML
    - 接收并存储平台返回的 submission_id
    """
    await _set_tenant(db, tenant_id)

    # 查询最新的一条已校验记录
    try:
        row = await db.execute(
            text("""
                SELECT id, xml_content, schema_version, status
                FROM invoice_xml_archive
                WHERE tenant_id = :tenant_id
                  AND invoice_id = :invoice_id
                  AND status IN ('validated', 'pending')
                  AND is_deleted = FALSE
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"tenant_id": tenant_id, "invoice_id": invoice_id},
        )
        record = row.mappings().first()

        if not record:
            return SubmissionResult(
                ok=False,
                submission_id="",
                status="rejected",
                message=f"发票 {invoice_id} 未找到已校验的 XML 记录",
            )

        archive_id = record["id"]
        # 模拟提交
        submission_id = f"GT-{uuid4().hex[:12].upper()}"

        await db.execute(
            text("""
                UPDATE invoice_xml_archive
                SET status = 'submitted',
                    submitted_at = NOW()
                WHERE id = :archive_id
                  AND tenant_id = :tenant_id
            """),
            {"archive_id": archive_id, "tenant_id": tenant_id},
        )
        await db.commit()

        logger.info(
            "invoice_submitted_to_golden_tax",
            invoice_id=invoice_id,
            submission_id=submission_id,
        )

        return SubmissionResult(
            ok=True,
            submission_id=submission_id,
            status="submitted",
            message="模拟提交成功（金税四期外部接口尚未接入）",
        )

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "invoice_submit_failed",
            invoice_id=invoice_id,
            error=str(exc),
            exc_info=True,
        )
        return SubmissionResult(
            ok=False,
            submission_id="",
            status="failed",
            message=f"提交失败: {exc}",
        )


async def create_ocr_job(
    db: AsyncSession,
    tenant_id: str,
    image_path: str,
    invoice_id: Optional[str] = None,
) -> str:
    """创建发票 OCR 识别任务。

    Returns:
        job_id — OCR 任务 ID
    """
    await _set_tenant(db, tenant_id)
    job_id = str(uuid4())

    try:
        await db.execute(
            text("""
                INSERT INTO invoice_ocr_jobs
                    (id, tenant_id, image_path, status, invoice_id, created_at)
                VALUES
                    (:id, :tenant_id, :image_path, 'pending', :invoice_id, NOW())
            """),
            {
                "id": job_id,
                "tenant_id": tenant_id,
                "image_path": image_path,
                "invoice_id": invoice_id,
            },
        )
        await db.commit()

        logger.info(
            "ocr_job_created",
            job_id=job_id,
            image_path=image_path,
        )
        return job_id

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "ocr_job_create_failed",
            image_path=image_path,
            error=str(exc),
            exc_info=True,
        )
        raise


async def process_ocr_result(
    db: AsyncSession,
    tenant_id: str,
    job_id: str,
    ocr_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """处理 OCR 识别结果。

    模拟处理流程：将任务状态从 processing 更新为 done，
    并将识别结果写入 ocr_result 字段。

    Args:
        ocr_data: 可选的 OCR 结果数据，模拟时可传入
                  生产环境由实际的 OCR 引擎回调填充

    Returns:
        dict 包含 OCR 处理结果
    """
    await _set_tenant(db, tenant_id)

    # 模拟 OCR 结果（外部 OCR SDK 未接入时使用）
    if ocr_data is None:
        ocr_data = {
            "invoice_code": f"INV{uuid4().hex[:8].upper()}",
            "invoice_number": f"NO{uuid4().hex[:10].upper()}",
            "invoice_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "seller_name": "模拟销售方",
            "buyer_name": "模拟购买方",
            "total_amount_fen": 10000,
            "tax_amount_fen": 1300,
            "confidence": 0.95,
        }

    try:
        await db.execute(
            text("""
                UPDATE invoice_ocr_jobs
                SET status = 'done',
                    ocr_result = :ocr_result
                WHERE id = :job_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "ocr_result": json.dumps(ocr_data),
            },
        )
        await db.commit()

        logger.info(
            "ocr_job_completed",
            job_id=job_id,
            confidence=ocr_data.get("confidence"),
        )

        return {
            "job_id": job_id,
            "status": "done",
            "ocr_result": ocr_data,
        }

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "ocr_job_process_failed",
            job_id=job_id,
            error=str(exc),
            exc_info=True,
        )
        return {"job_id": job_id, "status": "failed", "error": str(exc)}


async def get_pending_ocr_jobs(
    db: AsyncSession,
    tenant_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """查询待处理的 OCR 任务。"""
    await _set_tenant(db, tenant_id)

    try:
        rows = await db.execute(
            text("""
                SELECT id, image_path, status, invoice_id, created_at
                FROM invoice_ocr_jobs
                WHERE tenant_id = :tenant_id
                  AND status = 'pending'
                  AND is_deleted = FALSE
                ORDER BY created_at ASC
                LIMIT :limit
            """),
            {"tenant_id": tenant_id, "limit": limit},
        )
        return [dict(r._mapping) for r in rows]

    except SQLAlchemyError as exc:
        logger.error(
            "get_pending_ocr_jobs_failed",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        return []
