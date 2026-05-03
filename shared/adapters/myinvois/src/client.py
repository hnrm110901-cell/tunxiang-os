"""
MyInvois API 电子发票适配器 — LHDN Malaysia

文档: https://sdk.myinvois.hasil.gov.my
认证: OAuth2 Client Credentials
环境:
  - Sandbox: https://sandbox.myinvois.hasil.gov.my
  - Production: https://myinvois.hasil.gov.my
"""

import base64
import json
import time
import uuid
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()


class MyInvoisAdapter:
    """LHDN MyInvois 电子发票适配器

    支持: 发票提交、状态查询、取消、文档下载
    格式: JSON / XML / PDF
    """

    def __init__(self, config: dict[str, Any]):
        self.client_id = config["client_id"]
        self.client_secret = config["client_secret"]
        self.tax_id = config["tax_id"]  # TIN (Tax Identification Number)
        self.id_type = config.get("id_type", "NRIC")  # NRIC / PASSPORT / BRN / ARBN
        self.base_url = config.get(
            "base_url", "https://sandbox.myinvois.hasil.gov.my"
        )
        self.sandbox = config.get("sandbox", True)
        if not self.sandbox:
            self.base_url = "https://myinvois.hasil.gov.my"

        self._client = httpx.AsyncClient(timeout=60)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def _get_access_token(self) -> str:
        """OAuth2 Client Credentials 获取 token"""
        if self._access_token and time.time() < self._token_expires_at - 300:
            return self._access_token

        token_url = f"{self.base_url}/connect/token"
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        resp = await self._client.post(
            token_url,
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": "InvoicingAPI"},
        )
        data = resp.json()
        self._access_token = data.get("access_token", "")
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        logger.info("myinvois.token_refreshed", expires_in=data.get("expires_in"))
        return self._access_token

    async def _request(
        self, method: str, path: str, body: Optional[dict] = None
    ) -> dict:
        """通用 API 请求"""
        token = await self._get_access_token()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        resp = await self._client.request(method, url, headers=headers, json=body)
        result = resp.json()

        if resp.status_code >= 400:
            logger.error(
                "myinvois.api_error",
                status=resp.status_code,
                path=path,
                error=result.get("message", result.get("error", "unknown")),
            )

        return result

    async def submit_document(
        self,
        invoice_data: dict[str, Any],
        document_format: str = "JSON",
    ) -> dict:
        """提交电子发票到 LHDN

        Args:
            invoice_data: 发票数据（符合 MyInvois UBL 标准）
            document_format: JSON / XML / PDF

        Returns:
            { "acceptedDocuments": [...], "rejectedDocuments": [...] }
        """
        path = f"/api/v1.0/documentsubmissions"
        uuid_str = str(uuid.uuid4())
        payload = {
            "submission": {
                "invoice": invoice_data,
                "format": document_format,
                "submissionUUID": uuid_str,
            }
        }
        logger.info("myinvois.submitting", uuid=uuid_str)
        return await self._request("POST", path, payload)

    async def get_document(self, document_uuid: str) -> dict:
        """查询单张发票状态"""
        path = f"/api/v1.0/documents/{document_uuid}/raw"
        return await self._request("GET", path)

    async def get_document_status(self, document_uuid: str) -> dict:
        """查询发票处理状态"""
        path = f"/api/v1.0/documents/{document_uuid}/status"
        return await self._request("GET", path)

    async def cancel_document(
        self, document_uuid: str, reason: str = ""
    ) -> dict:
        """取消/作废发票（红冲）"""
        path = f"/api/v1.0/documents/{document_uuid}/cancel"
        payload = {
            "cancellation": {
                "reason": reason or "Cancel by merchant",
                "cancelledBy": self.tax_id,
            }
        }
        logger.info("myinvois.cancelling", uuid=document_uuid, reason=reason)
        return await self._request("PUT", path, payload)

    async def search_documents(
        self,
        date_from: str = "",
        date_to: str = "",
        status: str = "",
        page_size: int = 100,
    ) -> dict:
        """搜索发票（按日期范围、状态）"""
        path = f"/api/v1.0/documents?pageSize={page_size}"
        if date_from:
            path += f"&dateFrom={date_from}"
        if date_to:
            path += f"&dateTo={date_to}"
        if status:
            path += f"&status={status}"
        return await self._request("GET", path)

    async def get_recent_submissions(self, page_size: int = 10) -> dict:
        """查询最近提交记录"""
        path = f"/api/v1.0/documentsubmissions?pageSize={page_size}"
        return await self._request("GET", path)

    async def health_check(self) -> bool:
        """检查 MyInvois API 连通性"""
        try:
            token = await self._get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            resp = await self._client.get(
                f"{self.base_url}/api/v1.0/healthcheck",
                headers=headers,
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("myinvois.health_check_failed", error=str(exc))
            return False

    async def close(self):
        await self._client.aclose()
