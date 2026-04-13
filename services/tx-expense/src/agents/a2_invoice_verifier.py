"""
A2 发票核验 Agent
=================
职责：费用申请提交时对所有附件发票进行自动核验

触发时机：
  - 事件驱动：expense.application.submitted（申请提交时）
  - 手动触发：管理端批量重核验

处理流程（对每张发票并行执行）：
  1. OCR结构化识别（百度/阿里云）
  2. 金税四期真伪核验（<3秒）
  3. 集团级跨品牌跨门店去重
  4. 发票金额 vs 申请金额比对
  5. 科目自动建议（Claude API）
  6. 税额合规性校验
  7. 汇总结果写入申请单，高亮问题项

Agent铁律：
  - 识别结果自动填充供人确认，有争议项高亮，不自动驳回
  - verified_fake 发票高亮显示，最终由审批人决定
  - 集团级重复发票标记，不自动拦截（防误伤）
  - 所有处理结果写审计日志

量化目标：
  核验时间 8分钟/张→<30秒，重复发票集团级漏网率→0
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.expense_enums import AgentType, VerifyStatus
from ..services import invoice_verification_service as inv_svc

log = structlog.get_logger(__name__)

# 最大并发数：防止 OCR/金税接口限流
_MAX_CONCURRENCY = 5

# 可识别为发票的 MIME 类型前缀
_INVOICE_MIME_PREFIXES = ("image/", "application/pdf")


# =============================================================================
# 内部工具
# =============================================================================

async def _log_agent_job(
    tenant_id: UUID,
    job_type: str,
    trigger_source: str,
    application_id: Optional[UUID] = None,
    result: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """写入结构化审计日志（暂用 structlog，P1 接入 expense_agent_events 表）。"""
    log.info(
        "agent_job_executed",
        agent=AgentType.INVOICE_VERIFIER,
        job_type=job_type,
        trigger_source=trigger_source,
        tenant_id=str(tenant_id),
        application_id=str(application_id) if application_id else None,
        result=result,
        error=error,
    )


# =============================================================================
# 1. 文件下载（支持 Supabase Storage URL）
# =============================================================================

async def _download_file(file_url: str) -> Optional[bytes]:
    """
    从 Supabase Storage URL 下载文件内容。
    超时：10秒
    失败时返回 None（不抛出异常）
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(file_url, timeout=10.0)
            resp.raise_for_status()
            return resp.content
    except httpx.TimeoutException:
        log.warning("a2_download_file_timeout", file_url=file_url)
        return None
    except httpx.HTTPStatusError as exc:
        log.warning(
            "a2_download_file_http_error",
            file_url=file_url,
            status_code=exc.response.status_code,
        )
        return None
    except httpx.RequestError as exc:
        log.warning(
            "a2_download_file_request_error",
            file_url=file_url,
            error=str(exc),
        )
        return None


# =============================================================================
# 2. 金额比对
# =============================================================================

def check_amount_consistency(
    invoice_total_fen: int,
    application_item_amount_fen: int,
    tolerance_rate: float = 0.01,
) -> dict:
    """
    比对发票金额与申请金额。

    Args:
        invoice_total_fen:           发票含税总金额（分）
        application_item_amount_fen: 对应申请行金额（分）
        tolerance_rate:              允许偏差率，默认1%（发票含税/不含税差异）

    Returns:
        {
          "matched": bool,
          "deviation_rate": float,   # 偏差率，0.01 表示1%
          "message": str,
        }
    """
    if invoice_total_fen is None or application_item_amount_fen is None:
        return {
            "matched": False,
            "deviation_rate": None,
            "message": "金额数据不完整，无法比对",
        }

    if application_item_amount_fen == 0:
        matched = invoice_total_fen == 0
        return {
            "matched": matched,
            "deviation_rate": 0.0 if matched else 1.0,
            "message": "申请金额为0" if matched else "申请金额为0但发票金额非零",
        }

    deviation = abs(invoice_total_fen - application_item_amount_fen)
    deviation_rate = deviation / application_item_amount_fen
    matched = deviation_rate <= tolerance_rate

    if matched:
        message = (
            f"金额比对通过：发票 {invoice_total_fen / 100:.2f}元，"
            f"申请 {application_item_amount_fen / 100:.2f}元，"
            f"偏差 {deviation_rate * 100:.2f}%（≤{tolerance_rate * 100:.0f}%）"
        )
    else:
        message = (
            f"金额不一致：发票 {invoice_total_fen / 100:.2f}元，"
            f"申请 {application_item_amount_fen / 100:.2f}元，"
            f"偏差 {deviation_rate * 100:.2f}%（>{tolerance_rate * 100:.0f}%），请核实"
        )

    return {
        "matched": matched,
        "deviation_rate": round(deviation_rate, 6),
        "message": message,
    }


# =============================================================================
# 3. 生成核验报告摘要
# =============================================================================

def build_verification_summary(invoice_results: list[dict]) -> dict:
    """
    汇总多张发票核验结果，生成申请级报告。

    判断 needs_manual_review 的条件：
    - 任何发票 verified_fake=True
    - 任何发票 is_duplicate=True
    - 任何发票 amount_matched=False（金额不一致）
    - OCR 失败数 > 50%（超过一半发票识别失败）
    - 有严重税额合规问题

    Args:
        invoice_results: process_single_invoice 返回的摘要列表

    Returns:
        申请级核验报告 dict
    """
    total = len(invoice_results)
    verified_real = 0
    verified_fake = 0
    verify_failed = 0
    duplicates_found = 0
    amount_mismatches = 0
    compliance_issues = 0
    ocr_failed = 0

    review_reasons: list[str] = []

    for r in invoice_results:
        vs = r.get("verify_status", "")
        if vs == VerifyStatus.VERIFIED_REAL.value:
            verified_real += 1
        elif vs == VerifyStatus.VERIFIED_FAKE.value:
            verified_fake += 1
        elif vs == VerifyStatus.VERIFY_FAILED.value:
            verify_failed += 1

        if not r.get("ocr_success", True):
            ocr_failed += 1

        if r.get("is_duplicate"):
            duplicates_found += 1

        if r.get("amount_matched") is False:
            amount_mismatches += 1

        if r.get("compliance_issues"):
            compliance_issues += len(r["compliance_issues"])

    needs_manual_review = False

    if verified_fake > 0:
        needs_manual_review = True
        review_reasons.append(f"{verified_fake}张发票金税核验未通过（疑似虚假发票），请审批人确认")

    if duplicates_found > 0:
        needs_manual_review = True
        review_reasons.append(f"{duplicates_found}张发票在集团内存在重复记录，请确认是否重复报销")

    if amount_mismatches > 0:
        needs_manual_review = True
        review_reasons.append(f"{amount_mismatches}张发票金额与申请金额不一致（偏差>1%），请核实")

    if total > 0 and ocr_failed > total / 2:
        needs_manual_review = True
        review_reasons.append(
            f"{ocr_failed}/{total}张发票OCR识别失败（超过50%），请人工核对原件"
        )

    if compliance_issues > 0:
        needs_manual_review = True
        review_reasons.append(f"共{compliance_issues}项税额合规问题，请财务复核")

    return {
        "total_invoices": total,
        "verified_real": verified_real,
        "verified_fake": verified_fake,
        "verify_failed": verify_failed,
        "duplicates_found": duplicates_found,
        "amount_mismatches": amount_mismatches,
        "compliance_issues": compliance_issues,
        "needs_manual_review": needs_manual_review,
        "review_reasons": review_reasons,
        "invoice_summaries": invoice_results,
    }


# =============================================================================
# 4. 单张发票处理
# =============================================================================

async def process_single_invoice(
    db: AsyncSession,
    tenant_id: UUID,
    brand_id: UUID,
    store_id: UUID,
    invoice_id: UUID,
    application_id: UUID,
    file_bytes: bytes,
    file_type: str,
    expected_amount_fen: int = None,
) -> dict:
    """
    对单张已上传发票执行完整核验流程。
    调用 invoice_verification_service 各方法。
    返回核验摘要，包含所有问题项的高亮标记。

    Args:
        db:                    数据库会话
        tenant_id:             租户 ID
        brand_id:              品牌 ID
        store_id:              门店 ID
        invoice_id:            发票记录 ID（已在 invoices 表存在）
        application_id:        所属申请 ID
        file_bytes:            文件二进制内容
        file_type:             MIME 类型（如 image/jpeg）
        expected_amount_fen:   该发票对应的申请金额（分），可选

    Returns:
        核验摘要 dict，包含：ocr_success, verify_status, is_duplicate,
        amount_matched, compliance_issues, suggested_category 等
    """
    summary: dict = {
        "invoice_id": str(invoice_id),
        "ocr_success": False,
        "verify_status": VerifyStatus.PENDING.value,
        "verified_fake": False,
        "is_duplicate": False,
        "duplicate_of": None,
        "amount_matched": None,
        "amount_deviation_rate": None,
        "amount_message": None,
        "suggested_category": None,
        "compliance_issues": [],
        "needs_highlight": False,
        "error": None,
    }

    log.info(
        "a2_process_single_invoice_start",
        invoice_id=str(invoice_id),
        tenant_id=str(tenant_id),
        application_id=str(application_id),
    )

    try:
        # ── 步骤1：OCR 结构化识别 ─────────────────────────────────────────────
        ocr_result = await inv_svc.ocr_recognize(file_bytes, file_type)
        summary["ocr_success"] = ocr_result["success"]

        if not ocr_result["success"]:
            summary["error"] = f"OCR识别失败：{ocr_result.get('error')}"
            summary["needs_highlight"] = True
            log.warning(
                "a2_ocr_failed",
                invoice_id=str(invoice_id),
                error=ocr_result.get("error"),
            )
            # OCR 失败仍继续后续可执行的步骤（去重等），不直接返回
        else:
            summary["ocr_result"] = {
                "invoice_type": ocr_result.get("invoice_type"),
                "invoice_code": ocr_result.get("invoice_code"),
                "invoice_number": ocr_result.get("invoice_number"),
                "invoice_date": ocr_result.get("invoice_date"),
                "seller_name": ocr_result.get("seller_name"),
                "total_amount_fen": ocr_result.get("total_amount_fen"),
                "tax_amount_fen": ocr_result.get("tax_amount_fen"),
                "tax_rate": ocr_result.get("tax_rate"),
                "confidence": ocr_result.get("confidence"),
            }

        invoice_code = ocr_result.get("invoice_code")
        invoice_number = ocr_result.get("invoice_number")
        invoice_date_str = ocr_result.get("invoice_date")
        invoice_type = ocr_result.get("invoice_type")
        total_amount_fen = ocr_result.get("total_amount_fen")
        tax_amount_fen = ocr_result.get("tax_amount_fen")
        tax_rate = ocr_result.get("tax_rate")

        # ── 步骤2：金税四期真伪核验 ───────────────────────────────────────────
        if ocr_result["success"] and invoice_code and invoice_number and invoice_date_str and total_amount_fen:
            verify_result = await inv_svc.verify_with_tax_authority(
                invoice_code=invoice_code,
                invoice_number=invoice_number,
                invoice_date=invoice_date_str,
                total_amount_fen=total_amount_fen,
                buyer_tax_id=ocr_result.get("buyer_tax_id"),
            )
        else:
            verify_result = {
                "verified": False,
                "status": VerifyStatus.SKIPPED.value,
                "message": "OCR未成功或缺少必要字段，跳过金税核验",
                "raw_response": {},
            }

        summary["verify_status"] = verify_result["status"]
        summary["verify_message"] = verify_result.get("message")

        if verify_result["status"] == VerifyStatus.VERIFIED_FAKE.value:
            summary["verified_fake"] = True
            summary["needs_highlight"] = True
            log.warning(
                "a2_invoice_verified_fake",
                invoice_id=str(invoice_id),
                invoice_number=invoice_number,
                message=verify_result.get("message"),
            )

        # ── 步骤3：集团级跨品牌跨门店去重 ────────────────────────────────────
        if invoice_code and invoice_number and total_amount_fen:
            dedup_hash = inv_svc.compute_dedup_hash(invoice_code, invoice_number, total_amount_fen)
            duplicate_info = await inv_svc.check_duplicate(
                db=db,
                tenant_id=tenant_id,
                dedup_hash=dedup_hash,
                exclude_invoice_id=invoice_id,
            )
            if duplicate_info:
                summary["is_duplicate"] = True
                summary["duplicate_of"] = str(duplicate_info.get("duplicate_invoice_id"))
                summary["needs_highlight"] = True
                log.warning(
                    "a2_invoice_duplicate_found",
                    invoice_id=str(invoice_id),
                    duplicate_of=summary["duplicate_of"],
                    store_id=str(duplicate_info.get("store_id")),
                )

        # ── 步骤4：发票金额 vs 申请金额比对 ───────────────────────────────────
        if expected_amount_fen is not None and total_amount_fen is not None:
            amount_check = check_amount_consistency(
                invoice_total_fen=total_amount_fen,
                application_item_amount_fen=expected_amount_fen,
            )
            summary["amount_matched"] = amount_check["matched"]
            summary["amount_deviation_rate"] = amount_check["deviation_rate"]
            summary["amount_message"] = amount_check["message"]
            if not amount_check["matched"]:
                summary["needs_highlight"] = True

        # ── 步骤5：科目自动建议（Claude API）─────────────────────────────────
        if ocr_result["success"]:
            seller_name = ocr_result.get("seller_name") or ""
            items = ocr_result.get("items") or []
            items_desc = "、".join(
                item.get("name", "") for item in items if item.get("name")
            ) or ""

            # 从数据库获取该租户的费用科目列表
            try:
                cats_result = await db.execute(
                    text(
                        "SELECT id, name, code FROM expense_categories "
                        "WHERE tenant_id = :tenant_id AND is_deleted = FALSE "
                        "ORDER BY name LIMIT 50"
                    ),
                    {"tenant_id": str(tenant_id)},
                )
                existing_categories = [
                    {"id": str(row["id"]), "name": row["name"], "code": row.get("code", "")}
                    for row in cats_result.mappings().all()
                ]
            except Exception as cat_exc:
                log.warning(
                    "a2_fetch_categories_failed",
                    tenant_id=str(tenant_id),
                    error=str(cat_exc),
                )
                existing_categories = []

            category_suggestion = await inv_svc.suggest_category(
                seller_name=seller_name,
                items_description=items_desc,
                invoice_type=invoice_type or "",
                existing_categories=existing_categories,
            )
            summary["suggested_category"] = category_suggestion

        # ── 步骤6：税额合规性校验 ─────────────────────────────────────────────
        if invoice_type and total_amount_fen is not None and tax_amount_fen is not None and tax_rate is not None:
            tax_issues = inv_svc.check_tax_compliance(
                invoice_type=invoice_type,
                total_amount_fen=total_amount_fen,
                tax_amount_fen=tax_amount_fen,
                tax_rate=tax_rate,
            )
            summary["compliance_issues"] = tax_issues
            if tax_issues:
                summary["needs_highlight"] = True
                log.warning(
                    "a2_tax_compliance_issues",
                    invoice_id=str(invoice_id),
                    issues=tax_issues,
                )

        log.info(
            "a2_process_single_invoice_done",
            invoice_id=str(invoice_id),
            needs_highlight=summary["needs_highlight"],
            verify_status=summary["verify_status"],
            is_duplicate=summary["is_duplicate"],
        )
        return summary

    except Exception as exc:  # noqa: BLE001 — 兜底，单张失败不阻断批量流程
        error_msg = f"{type(exc).__name__}: {exc}"
        summary["error"] = error_msg
        summary["needs_highlight"] = True
        log.error(
            "a2_process_single_invoice_error",
            invoice_id=str(invoice_id),
            tenant_id=str(tenant_id),
            error=error_msg,
            exc_info=True,
        )
        return summary


# =============================================================================
# 5. 申请级批量处理（核心入口）
# =============================================================================

async def verify_application_invoices(
    db: AsyncSession,
    tenant_id: UUID,
    application_id: UUID,
) -> dict:
    """
    对一个费用申请的所有附件发票并行核验。

    流程：
    1. 查询该申请的所有附件（expense_attachments）
    2. 过滤出图片/PDF类型的附件（可能是发票）
    3. 下载文件内容（从 file_url）
    4. 并行调用 process_single_invoice（最多5并发）
    5. 汇总结果，生成申请级核验报告
    6. 将核验结果写入 expense_applications.metadata['invoice_verification']
    7. 返回汇总报告

    Returns:
        {
          "application_id": str,
          "total_invoices": int,
          "verified_real": int,
          "verified_fake": int,
          "verify_failed": int,
          "duplicates_found": int,
          "amount_mismatches": int,
          "compliance_issues": int,
          "needs_manual_review": bool,
          "review_reasons": list[str],
          "invoice_summaries": list[dict],
        }
    """
    report: dict = {
        "application_id": str(application_id),
        "total_invoices": 0,
        "verified_real": 0,
        "verified_fake": 0,
        "verify_failed": 0,
        "duplicates_found": 0,
        "amount_mismatches": 0,
        "compliance_issues": 0,
        "needs_manual_review": False,
        "review_reasons": [],
        "invoice_summaries": [],
        "error": None,
    }

    log.info(
        "a2_verify_application_invoices_start",
        tenant_id=str(tenant_id),
        application_id=str(application_id),
    )

    # ── 步骤1：查询该申请的所有附件 ──────────────────────────────────────────
    try:
        attachments_result = await db.execute(
            text(
                "SELECT id, file_name, file_url, file_type, file_size, uploaded_by "
                "FROM expense_attachments "
                "WHERE tenant_id = :tenant_id "
                "  AND application_id = :application_id "
                "  AND is_deleted = FALSE "
                "ORDER BY created_at"
            ),
            {
                "tenant_id": str(tenant_id),
                "application_id": str(application_id),
            },
        )
        all_attachments = list(attachments_result.mappings().all())
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        report["error"] = f"查询附件失败：{error_msg}"
        report["needs_manual_review"] = True
        report["review_reasons"].append("附件查询失败，请人工核对")
        log.error(
            "a2_fetch_attachments_error",
            tenant_id=str(tenant_id),
            application_id=str(application_id),
            error=error_msg,
            exc_info=True,
        )
        return report

    # ── 步骤2：过滤可能是发票的附件（图片或 PDF）────────────────────────────
    invoice_attachments = [
        att for att in all_attachments
        if att.get("file_type") and any(
            att["file_type"].startswith(prefix) for prefix in _INVOICE_MIME_PREFIXES
        )
    ]

    if not invoice_attachments:
        log.info(
            "a2_no_invoice_attachments",
            tenant_id=str(tenant_id),
            application_id=str(application_id),
            total_attachments=len(all_attachments),
        )
        return report

    # ── 查询申请基本信息（brand_id、store_id）────────────────────────────────
    try:
        app_result = await db.execute(
            text(
                "SELECT brand_id, store_id "
                "FROM expense_applications "
                "WHERE tenant_id = :tenant_id AND id = :application_id AND is_deleted = FALSE"
            ),
            {"tenant_id": str(tenant_id), "application_id": str(application_id)},
        )
        app_row = app_result.mappings().one_or_none()
    except Exception as exc:
        app_row = None
        log.warning(
            "a2_fetch_application_info_failed",
            tenant_id=str(tenant_id),
            application_id=str(application_id),
            error=str(exc),
        )

    brand_id = UUID(str(app_row["brand_id"])) if app_row and app_row.get("brand_id") else uuid.uuid4()
    store_id = UUID(str(app_row["store_id"])) if app_row and app_row.get("store_id") else uuid.uuid4()

    # ── 步骤3&4：并行下载并核验（最多5并发）──────────────────────────────────
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _verify_one_attachment(att: dict) -> Optional[dict]:
        """下载单个附件并执行核验，受并发信号量控制。"""
        async with semaphore:
            att_id = att["id"]
            file_url = att["file_url"]
            file_type = att.get("file_type", "application/octet-stream")
            file_name = att.get("file_name", "")

            # ── 步骤3：下载文件 ────────────────────────────────────────────────
            file_bytes = await _download_file(file_url)
            if file_bytes is None:
                log.warning(
                    "a2_attachment_download_failed",
                    attachment_id=str(att_id),
                    file_url=file_url,
                )
                # 下载失败：返回标记 needs_highlight 的摘要，不阻断整体流程
                return {
                    "invoice_id": str(att_id),
                    "file_name": file_name,
                    "ocr_success": False,
                    "verify_status": VerifyStatus.VERIFY_FAILED.value,
                    "verified_fake": False,
                    "is_duplicate": False,
                    "duplicate_of": None,
                    "amount_matched": None,
                    "amount_deviation_rate": None,
                    "amount_message": None,
                    "suggested_category": None,
                    "compliance_issues": [],
                    "needs_highlight": True,
                    "error": f"文件下载失败：{file_url}",
                }

            # ── 步骤4：核验 ───────────────────────────────────────────────────
            invoice_id = uuid.uuid4()  # 本次核验生成的临时 ID（未落表）
            result = await process_single_invoice(
                db=db,
                tenant_id=tenant_id,
                brand_id=brand_id,
                store_id=store_id,
                invoice_id=invoice_id,
                application_id=application_id,
                file_bytes=file_bytes,
                file_type=file_type,
                expected_amount_fen=None,  # 批量核验暂不比对逐项金额
            )
            result["file_name"] = file_name
            result["attachment_id"] = str(att_id)
            return result

    tasks = [_verify_one_attachment(att) for att in invoice_attachments]
    invoice_results = await asyncio.gather(*tasks, return_exceptions=False)

    # 过滤 None（理论上不会出现，防御性处理）
    valid_results = [r for r in invoice_results if r is not None]

    # ── 步骤5：汇总结果 ───────────────────────────────────────────────────────
    summary = build_verification_summary(valid_results)
    report.update(summary)

    # ── 步骤6：将核验结果写入 expense_applications.metadata ──────────────────
    import json as _json
    verification_meta = {
        "verified_at": str(asyncio.get_event_loop().time()),  # 单调时钟，仅供参考
        "total_invoices": report["total_invoices"],
        "verified_real": report["verified_real"],
        "verified_fake": report["verified_fake"],
        "duplicates_found": report["duplicates_found"],
        "amount_mismatches": report["amount_mismatches"],
        "compliance_issues": report["compliance_issues"],
        "needs_manual_review": report["needs_manual_review"],
        "review_reasons": report["review_reasons"],
    }
    try:
        await db.execute(
            text(
                "UPDATE expense_applications "
                "SET metadata = COALESCE(metadata, '{}'::jsonb) || :patch, "
                "    updated_at = NOW() "
                "WHERE tenant_id = :tenant_id AND id = :application_id"
            ),
            {
                "patch": _json.dumps({"invoice_verification": verification_meta}),
                "tenant_id": str(tenant_id),
                "application_id": str(application_id),
            },
        )
        await db.flush()
        log.info(
            "a2_metadata_written",
            application_id=str(application_id),
            needs_manual_review=report["needs_manual_review"],
        )
    except Exception as exc:
        log.warning(
            "a2_metadata_write_failed",
            application_id=str(application_id),
            error=str(exc),
        )
        # 写 metadata 失败不阻断核验报告返回

    log.info(
        "a2_verify_application_invoices_done",
        tenant_id=str(tenant_id),
        application_id=str(application_id),
        total_invoices=report["total_invoices"],
        verified_fake=report["verified_fake"],
        duplicates_found=report["duplicates_found"],
        needs_manual_review=report["needs_manual_review"],
    )
    return report


# =============================================================================
# 6. 批量重核验（手动触发）
# =============================================================================

async def reverify_invoices(
    db: AsyncSession,
    tenant_id: UUID,
    invoice_ids: list[UUID],
) -> dict:
    """
    管理端手动批量重核验指定发票。

    Args:
        invoice_ids: 需要重核验的发票 ID 列表

    Returns:
        {
          "total": int,
          "success": int,
          "failed": int,
          "results": list[dict],
        }
    """
    summary = {"total": len(invoice_ids), "success": 0, "failed": 0, "results": []}
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _reverify_one(inv_id: UUID) -> dict:
        async with semaphore:
            try:
                # 查询发票记录
                inv_result = await db.execute(
                    text(
                        "SELECT id, brand_id, store_id, file_url, file_type, application_id "
                        "FROM invoices "
                        "WHERE tenant_id = :tenant_id AND id = :inv_id AND is_deleted = FALSE"
                    ),
                    {"tenant_id": str(tenant_id), "inv_id": str(inv_id)},
                )
                row = inv_result.mappings().one_or_none()
                if row is None:
                    return {
                        "invoice_id": str(inv_id),
                        "success": False,
                        "error": "发票记录不存在",
                    }

                file_bytes = await _download_file(row["file_url"])
                if file_bytes is None:
                    return {
                        "invoice_id": str(inv_id),
                        "success": False,
                        "error": "文件下载失败",
                    }

                result = await process_single_invoice(
                    db=db,
                    tenant_id=tenant_id,
                    brand_id=UUID(str(row["brand_id"])),
                    store_id=UUID(str(row["store_id"])),
                    invoice_id=inv_id,
                    application_id=UUID(str(row["application_id"])) if row.get("application_id") else inv_id,
                    file_bytes=file_bytes,
                    file_type=row.get("file_type") or "image/jpeg",
                )
                result["success"] = True
                return result

            except Exception as exc:  # noqa: BLE001
                error_msg = f"{type(exc).__name__}: {exc}"
                log.error(
                    "a2_reverify_one_error",
                    invoice_id=str(inv_id),
                    tenant_id=str(tenant_id),
                    error=error_msg,
                    exc_info=True,
                )
                return {"invoice_id": str(inv_id), "success": False, "error": error_msg}

    tasks = [_reverify_one(inv_id) for inv_id in invoice_ids]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    for r in results:
        if r.get("success"):
            summary["success"] += 1
        else:
            summary["failed"] += 1
        summary["results"].append(r)

    return summary


# =============================================================================
# 7. Agent 主入口（统一调度）
# =============================================================================

async def run(
    db: AsyncSession,
    tenant_id: UUID,
    trigger: str,
    payload: dict,
) -> dict:
    """
    A2 Agent 统一入口，由事件消费者和管理端调用。

    trigger 值：
      "application_submitted" → verify_application_invoices(payload["application_id"])
      "manual_reverify"       → 批量重核验 payload["invoice_ids"]

    所有异常捕获记录日志，不向上抛出（Agent 失败不影响业务主流程）。
    返回处理结果 dict（总是返回，不抛异常）。
    """
    log.info(
        "a2_agent_run_start",
        agent=AgentType.INVOICE_VERIFIER,
        trigger=trigger,
        tenant_id=str(tenant_id),
    )

    try:
        if trigger == "application_submitted":
            application_id = payload["application_id"]
            if not isinstance(application_id, UUID):
                application_id = UUID(str(application_id))
            result = await verify_application_invoices(
                db=db,
                tenant_id=tenant_id,
                application_id=application_id,
            )
            await _log_agent_job(
                tenant_id=tenant_id,
                job_type="verify_application_invoices",
                trigger_source="event_application_submitted",
                application_id=application_id,
                result={
                    "total_invoices": result.get("total_invoices"),
                    "verified_fake": result.get("verified_fake"),
                    "duplicates_found": result.get("duplicates_found"),
                    "needs_manual_review": result.get("needs_manual_review"),
                },
            )
            return result

        elif trigger == "manual_reverify":
            raw_ids = payload.get("invoice_ids", [])
            invoice_ids = [UUID(str(i)) for i in raw_ids]
            result = await reverify_invoices(
                db=db,
                tenant_id=tenant_id,
                invoice_ids=invoice_ids,
            )
            await _log_agent_job(
                tenant_id=tenant_id,
                job_type="reverify_invoices",
                trigger_source="manual",
                result={
                    "total": result.get("total"),
                    "success": result.get("success"),
                    "failed": result.get("failed"),
                },
            )
            return result

        else:
            unknown_result = {
                "error": f"未知 trigger 类型: {trigger}",
                "trigger": trigger,
            }
            log.error(
                "a2_agent_unknown_trigger",
                agent=AgentType.INVOICE_VERIFIER,
                trigger=trigger,
                tenant_id=str(tenant_id),
            )
            return unknown_result

    except Exception as exc:  # noqa: BLE001 — 最外层兜底
        error_msg = f"{type(exc).__name__}: {exc}"
        log.error(
            "a2_agent_run_unhandled_error",
            agent=AgentType.INVOICE_VERIFIER,
            trigger=trigger,
            tenant_id=str(tenant_id),
            error=error_msg,
            exc_info=True,
        )
        await _log_agent_job(
            tenant_id=tenant_id,
            job_type=trigger,
            trigger_source="unknown",
            result=None,
            error=error_msg,
        )
        return {
            "trigger": trigger,
            "error": error_msg,
        }
