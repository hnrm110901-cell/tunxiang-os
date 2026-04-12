"""离线知识查询 — Mac mini 本地 pgvector 检索

断网时仍可查询已同步到本地的知识库：
- 使用 CoreML 本地 embedding（或 TF-IDF 降级）
- 查询本地 PostgreSQL 的 knowledge_chunks 表
- 简化版路由（无需云端 LLM）
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

_COREML_URL = os.environ.get("COREML_BRIDGE_URL", "http://localhost:8100")
_LOCAL_DB_URL = os.environ.get("LOCAL_DATABASE_URL", "")


class OfflineKnowledgeService:
    """离线知识查询服务"""

    @staticmethod
    async def search(
        query: str,
        collection: str,
        tenant_id: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """本地向量检索。

        1. 本地 embedding（CoreML → TF-IDF fallback）
        2. pgvector cosine 搜索本地 knowledge_chunks
        """
        if not query or not query.strip():
            return []

        # 1. 获取查询向量
        embedding = await _get_local_embedding(query)
        if not embedding:
            logger.warning("offline_search_no_embedding")
            return []

        # 2. 本地 pgvector 检索
        try:
            # TODO: 使用本地 DB session
            # 当前返回空列表，等本地 DB 连接就绪后启用
            logger.info(
                "offline_search_invoked",
                collection=collection,
                tenant_id=tenant_id,
                top_k=top_k,
            )
            return []
        except ValueError as exc:
            logger.warning("offline_search_value_error", error=str(exc))
            return []

    @staticmethod
    async def is_available() -> bool:
        """检查本地知识库是否可用"""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{_COREML_URL}/health")
                return resp.status_code == 200
        except httpx.ConnectError:
            return False
        except httpx.TimeoutException:
            return False


async def _get_local_embedding(text: str) -> list[float] | None:
    """获取本地 embedding（CoreML → TF-IDF 降级）"""
    # 优先尝试 CoreML bridge
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{_COREML_URL}/embed",
                json={"text": text},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("embedding", [])
    except httpx.ConnectError:
        pass
    except httpx.TimeoutException:
        pass

    # 降级：TF-IDF
    try:
        from shared.vector_store.embeddings import EmbeddingService
        return EmbeddingService._tfidf_embed(text)
    except ImportError:
        logger.warning("tfidf_fallback_import_error")
        return None
    except AttributeError:
        logger.warning("tfidf_fallback_attribute_error")
        return None
