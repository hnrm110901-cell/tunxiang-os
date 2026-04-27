"""电子签章 SDK 封装 — 法大大 / e签宝（当前为 Mock 实现）

环境变量:
  ESIGN_PROVIDER         -- fadada / esignbao (默认 mock)
  ESIGN_APP_ID           -- 应用ID
  ESIGN_APP_SECRET       -- 应用密钥
  ESIGN_CALLBACK_URL     -- 签署完成回调URL

当 ESIGN_APP_ID 未配置时自动进入 Mock 模式，仅打印日志不调用第三方接口。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ESignSDK:
    """电子签章 SDK 封装（法大大 / e签宝）-- 当前为 Mock 实现

    后续接入法大大/e签宝时替换内部逻辑，接口保持不变。
    """

    def __init__(self) -> None:
        self._provider = os.getenv("ESIGN_PROVIDER", "mock")
        self._app_id = os.getenv("ESIGN_APP_ID", "")
        self._app_secret = os.getenv("ESIGN_APP_SECRET", "")
        self._callback_url = os.getenv("ESIGN_CALLBACK_URL", "")
        self._is_mock = not self._app_id

        if self._is_mock:
            logger.info(
                "esign_sdk.mock_mode",
                provider=self._provider,
                note="ESIGN_APP_ID 未配置，使用 Mock 模式",
            )
        else:
            logger.info(
                "esign_sdk.initialized",
                provider=self._provider,
                app_id=self._app_id[:8] + "****",
            )

    async def create_document(
        self,
        content_html: str,
        signers: list[dict[str, Any]],
    ) -> str:
        """创建待签署文档

        Args:
            content_html: 合同HTML内容
            signers: 签署人列表 [{"name": "张三", "id_card": "...", "type": "employee|company"}]

        Returns:
            第三方文档 doc_id
        """
        if self._is_mock:
            doc_id = f"MOCK-DOC-{uuid.uuid4().hex[:12].upper()}"
            logger.info(
                "esign_sdk.mock_create_document",
                doc_id=doc_id,
                signers_count=len(signers),
            )
            return doc_id

        # TODO: 接入法大大/e签宝 API
        raise NotImplementedError(f"暂不支持 provider: {self._provider}")

    async def get_sign_url(
        self,
        doc_id: str,
        signer_type: str = "employee",
    ) -> str:
        """获取签署页面 URL

        Args:
            doc_id: 文档ID
            signer_type: 签署人类型 employee / company

        Returns:
            签署页面URL
        """
        if self._is_mock:
            token = uuid.uuid4().hex[:16]
            url = f"https://esign.mock.tunxiang.local/sign/{doc_id}?type={signer_type}&token={token}"
            logger.info("esign_sdk.mock_get_sign_url", doc_id=doc_id, signer_type=signer_type)
            return url

        raise NotImplementedError(f"暂不支持 provider: {self._provider}")

    async def get_document_status(self, doc_id: str) -> dict[str, Any]:
        """查询文档签署状态

        Args:
            doc_id: 文档ID

        Returns:
            {"doc_id": str, "status": str, "signers": [...], "updated_at": str}
        """
        if self._is_mock:
            now_iso = datetime.now(timezone.utc).isoformat()
            logger.info("esign_sdk.mock_get_status", doc_id=doc_id)
            return {
                "doc_id": doc_id,
                "status": "completed",
                "signers": [
                    {"type": "employee", "signed": True, "signed_at": now_iso},
                    {"type": "company", "signed": True, "signed_at": now_iso},
                ],
                "updated_at": now_iso,
            }

        raise NotImplementedError(f"暂不支持 provider: {self._provider}")

    async def download_signed_document(self, doc_id: str) -> bytes:
        """下载已签署的文档 PDF 字节

        Args:
            doc_id: 文档ID

        Returns:
            签署完成的 PDF 文件字节（Mock 返回最小合法 PDF）
        """
        if self._is_mock:
            logger.info("esign_sdk.mock_download", doc_id=doc_id)
            # 最小合法 PDF 占位
            return (
                b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>"
                b"endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>"
                b"endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]/"
                b"Parent 2 0 R>>endobj\nxref\n0 4\n"
                b"0000000000 65535 f \n0000000009 00000 n \n"
                b"0000000058 00000 n \n0000000115 00000 n \n"
                b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
            )

        raise NotImplementedError(f"暂不支持 provider: {self._provider}")

    async def revoke_sign_task(self, doc_id: str, reason: str = "") -> dict[str, Any]:
        """撤销签署任务

        Args:
            doc_id: 文档ID
            reason: 撤销原因

        Returns:
            {"doc_id": str, "status": "revoked"}
        """
        if self._is_mock:
            logger.info("esign_sdk.mock_revoke", doc_id=doc_id, reason=reason)
            return {
                "doc_id": doc_id,
                "status": "revoked",
                "revoked_at": datetime.now(timezone.utc).isoformat(),
            }

        raise NotImplementedError(f"暂不支持 provider: {self._provider}")
