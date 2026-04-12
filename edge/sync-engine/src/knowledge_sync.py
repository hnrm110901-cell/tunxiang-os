"""知识库同步策略 — 云端 → Mac mini 本地

同步策略：
- 全量同步：首次部署时拉取所有 published 的文档和块
- 增量同步：每 5 分钟拉取 updated_at > watermark 的变更
- 仅同步 status='published' 的文档
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()


class KnowledgeSyncStrategy:
    """知识库专用同步策略"""

    def __init__(
        self,
        cloud_api_url: str,
        sync_batch_size: int = 200,
    ) -> None:
        self.cloud_api_url = cloud_api_url.rstrip("/")
        self.batch_size = sync_batch_size
        self._last_sync_at: datetime | None = None

    async def full_sync(
        self,
        local_pool: Any,
        tenant_id: str,
    ) -> dict[str, int]:
        """全量同步（首次部署 / 重置后）。

        从云端拉取所有 published 文档 + 块 → 写入本地 PG。
        """
        import httpx

        documents_synced = 0
        chunks_synced = 0

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # 1. 拉取文档列表
                resp = await client.get(
                    f"{self.cloud_api_url}/api/v1/knowledge/documents",
                    params={"tenant_id": tenant_id, "status": "published", "size": 1000},
                )
                if resp.status_code != 200:
                    logger.warning("knowledge_full_sync_docs_failed", status=resp.status_code)
                    return {"documents": 0, "chunks": 0}

                data = resp.json()
                documents = data.get("data", {}).get("items", [])

                for doc in documents:
                    doc_id = doc.get("id", "")
                    # 2. 拉取每个文档的块
                    chunks_resp = await client.get(
                        f"{self.cloud_api_url}/api/v1/knowledge/documents/{doc_id}/chunks",
                        params={"tenant_id": tenant_id, "size": 1000},
                    )
                    if chunks_resp.status_code == 200:
                        chunks_data = chunks_resp.json()
                        chunks = chunks_data.get("data", {}).get("items", [])
                        # TODO: 写入本地 PG（含向量）
                        chunks_synced += len(chunks)

                    documents_synced += 1

            self._last_sync_at = datetime.now(timezone.utc)

            logger.info(
                "knowledge_full_sync_done",
                tenant_id=tenant_id,
                documents=documents_synced,
                chunks=chunks_synced,
            )

        except httpx.ConnectError as exc:
            logger.warning("knowledge_full_sync_connect_error", error=str(exc))
        except httpx.TimeoutException as exc:
            logger.warning("knowledge_full_sync_timeout", error=str(exc))

        return {"documents": documents_synced, "chunks": chunks_synced}

    async def incremental_sync(
        self,
        local_pool: Any,
        tenant_id: str,
    ) -> dict[str, int]:
        """增量同步（每 5 分钟）。

        仅拉取 updated_at > last_sync_at 且 status='published' 的变更。
        """
        import httpx

        watermark = self._last_sync_at or datetime(2020, 1, 1, tzinfo=timezone.utc)
        chunks_synced = 0

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.cloud_api_url}/api/v1/knowledge/documents",
                    params={
                        "tenant_id": tenant_id,
                        "status": "published",
                        "updated_after": watermark.isoformat(),
                        "size": self.batch_size,
                    },
                )

                if resp.status_code != 200:
                    return {"chunks": 0}

                data = resp.json()
                documents = data.get("data", {}).get("items", [])

                for doc in documents:
                    doc_id = doc.get("id", "")
                    chunks_resp = await client.get(
                        f"{self.cloud_api_url}/api/v1/knowledge/documents/{doc_id}/chunks",
                        params={"tenant_id": tenant_id, "size": 1000},
                    )
                    if chunks_resp.status_code == 200:
                        chunks_data = chunks_resp.json()
                        chunks = chunks_data.get("data", {}).get("items", [])
                        # TODO: UPSERT 到本地 PG
                        chunks_synced += len(chunks)

            self._last_sync_at = datetime.now(timezone.utc)

            if chunks_synced > 0:
                logger.info(
                    "knowledge_incremental_sync_done",
                    tenant_id=tenant_id,
                    chunks=chunks_synced,
                )

        except httpx.ConnectError as exc:
            logger.warning("knowledge_incremental_sync_connect_error", error=str(exc))
        except httpx.TimeoutException as exc:
            logger.warning("knowledge_incremental_sync_timeout", error=str(exc))

        return {"chunks": chunks_synced}
