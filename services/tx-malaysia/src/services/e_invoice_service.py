"""LHDN MyInvois e-Invoice 业务服务

职责：
  - 提交电子发票到 MyInvois
  - 查询发票处理状态
  - 取消/作废发票
  - 下载 PDF/XML

LHDN Phase 合规时间表：
  Phase 1 (2024-08): 年营收 ≥1亿 RM 的企业
  Phase 2 (2025-01): 年营收 ≥2500万 RM 的企业
  Phase 3 (2025-07): 所有企业（含 SMEs）
  Phase 4 (2026-01): 所有开票方
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from shared.adapters.myinvois.src.client import MyInvoisAdapter

logger = structlog.get_logger()

# LHDN Phase 生效日期（用于合规路由）
LHDN_PHASES: list[dict[str, Any]] = [
    {"phase": 1, "date": "2024-08-01", "min_revenue_rm": 100_000_000},
    {"phase": 2, "date": "2025-01-01", "min_revenue_rm": 25_000_000},
    {"phase": 3, "date": "2025-07-01", "min_revenue_rm": 0},
    {"phase": 4, "date": "2026-01-01", "min_revenue_rm": 0},
]


def get_current_phase() -> int:
    """根据当前日期判断 LHDN Phase"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for phase in reversed(LHDN_PHASES):
        if today >= phase["date"]:
            return phase["phase"]
    return 1


class EinvoiceService:
    """MyInvois e-Invoice 服务"""

    def __init__(self, myinvois_adapter: Optional[MyInvoisAdapter] = None) -> None:
        self._adapter = myinvois_adapter or MyInvoisAdapter(
            config={
                "client_id": "",
                "client_secret": "",
                "tax_id": "",
            }
        )

    async def submit_invoice(
        self,
        invoice_data: dict[str, Any],
        tenant_id: str,
        store_id: str,
        document_format: str = "JSON",
    ) -> dict[str, Any]:
        """提交电子发票到 LHDN MyInvois

        根据 LHDN 规范，发票数据需符合 UBL 2.1 / PEPPOL BIS 标准。

        Returns:
            {acceptedDocuments, rejectedDocuments, submission_uuid}
        """
        log = logger.bind(tenant_id=tenant_id, store_id=store_id)
        log.info("myinvois.submit_invoice")

        result = await self._adapter.submit_document(
            invoice_data=invoice_data,
            document_format=document_format,
        )

        accepted = result.get("acceptedDocuments", [])
        rejected = result.get("rejectedDocuments", [])

        if rejected:
            log.warning(
                "myinvois.documents_rejected",
                count=len(rejected),
                errors=[r.get("error", {}) for r in rejected],
            )

        log.info(
            "myinvois.submit_result",
            accepted=len(accepted),
            rejected=len(rejected),
        )

        return {
            "submission_uuid": result.get("submissionUUID", ""),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted_documents": [
                {
                    "uuid": doc.get("uuid", ""),
                    "status": doc.get("status", ""),
                }
                for doc in accepted
            ],
            "rejected_documents": [
                {
                    "uuid": doc.get("uuid", ""),
                    "error": doc.get("error", {}),
                }
                for doc in rejected
            ],
        }

    async def query_invoice_status(
        self,
        document_uuid: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """查询发票处理状态"""
        log = logger.bind(tenant_id=tenant_id, document_uuid=document_uuid)
        log.info("myinvois.query_status")

        result = await self._adapter.get_document_status(document_uuid)

        status = result.get("status", "unknown")
        log.info("myinvois.status_result", status=status)

        return {
            "document_uuid": document_uuid,
            "status": status,
            "raw": result,
        }

    async def cancel_invoice(
        self,
        document_uuid: str,
        tenant_id: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """取消/冲红电子发票"""
        log = logger.bind(tenant_id=tenant_id, document_uuid=document_uuid)
        log.info("myinvois.cancel_invoice", reason=reason)

        result = await self._adapter.cancel_document(
            document_uuid=document_uuid,
            reason=reason,
        )

        return {
            "document_uuid": document_uuid,
            "result": result,
        }

    async def get_invoice_detail(
        self,
        document_uuid: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """获取发票完整数据"""
        log = logger.bind(tenant_id=tenant_id, document_uuid=document_uuid)
        log.info("myinvois.get_detail")

        result = await self._adapter.get_document(document_uuid)

        return {
            "document_uuid": document_uuid,
            "data": result,
        }

    async def search_invoices(
        self,
        tenant_id: str,
        date_from: str = "",
        date_to: str = "",
        status: str = "",
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """批量搜索发票"""
        log = logger.bind(tenant_id=tenant_id)
        log.info("myinvois.search", date_from=date_from, date_to=date_to)

        result = await self._adapter.search_documents(
            date_from=date_from,
            date_to=date_to,
            status=status,
            page_size=page_size,
        )

        documents = result.get("documents", [])

        log.info("myinvois.search_result", count=len(documents))

        return [
            {
                "uuid": doc.get("uuid", ""),
                "status": doc.get("status", ""),
                "created_at": doc.get("createdAt", ""),
                "total_fen": doc.get("total", 0),
            }
            for doc in documents
        ]

    async def get_recent_submissions(
        self,
        tenant_id: str,
        page_size: int = 10,
    ) -> list[dict[str, Any]]:
        """查询近期提交记录"""
        log = logger.bind(tenant_id=tenant_id)
        log.info("myinvois.recent_submissions")

        result = await self._adapter.get_recent_submissions(page_size=page_size)

        submissions = result.get("submissions", [])

        return [
            {
                "uuid": sub.get("uuid", ""),
                "status": sub.get("status", ""),
                "document_count": sub.get("documentCount", 0),
                "created_at": sub.get("createdAt", ""),
            }
            for sub in submissions
        ]

    async def health_check(self) -> bool:
        """检查 MyInvois API 连通性"""
        return await self._adapter.health_check()
