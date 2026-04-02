"""知识检索服务 — 供Agent使用

提供tenant隔离的向量知识库检索能力：
- index_document: 索引单条文档
- search: 带tenant过滤的向量检索
- index_menu_knowledge: 从DB批量索引菜品信息
- index_decision_history: 索引Agent决策日志

Qdrant不可用时所有方法优雅降级（返回空/False），不影响主业务。
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Optional

import structlog

from shared.vector_store.client import QdrantClient
from shared.vector_store.embeddings import EmbeddingService
from shared.vector_store.indexes import get_vector_size

logger = structlog.get_logger()


class KnowledgeRetrievalService:
    """供Agent使用的知识检索服务（无状态，方法均为async）"""

    # ── 健康检查 ─────────────────────────────────────────────

    @staticmethod
    async def is_available() -> bool:
        """检查向量库是否可用"""
        return await QdrantClient.health_check()

    # ── 索引文档 ─────────────────────────────────────────────

    @staticmethod
    async def index_document(
        collection: str,
        doc_id: str,
        text: str,
        metadata: dict[str, Any],
        tenant_id: str,
    ) -> bool:
        """索引单条文档。

        步骤：
        1. 向量化文本
        2. payload中加入tenant_id（用于过滤隔离）
        3. upsert到Qdrant

        Qdrant不可用时返回False，不抛异常。
        """
        if not text or not text.strip():
            logger.warning("index_document_empty_text", doc_id=doc_id)
            return False

        # 确保collection存在
        vector_size = get_vector_size(collection)
        ok = await QdrantClient.create_collection_if_not_exists(collection, vector_size)
        if not ok:
            logger.warning("index_document_collection_unavailable", collection=collection)
            return False

        # 向量化
        vector = await EmbeddingService.embed_text(text)

        # 构建payload（含tenant_id）
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "doc_id": doc_id,
            "text": text[:500],  # 存储前500字符供调试
            **metadata,
        }

        # 使用doc_id的hash作为Qdrant点ID（整数）
        point_id = _doc_id_to_int(doc_id)

        point = {
            "id": point_id,
            "vector": vector,
            "payload": payload,
        }

        success = await QdrantClient.upsert(collection, [point])
        if success:
            logger.info(
                "index_document_ok",
                collection=collection,
                doc_id=doc_id,
                tenant_id=tenant_id,
            )
        return success

    # ── 批量索引 ─────────────────────────────────────────────

    @staticmethod
    async def index_documents_batch(
        collection: str,
        documents: list[dict[str, Any]],
        tenant_id: str,
        batch_size: int = 50,
    ) -> dict[str, int]:
        """批量索引文档（大量文档一次性写入）。

        documents格式：[{doc_id, text, metadata}]
        返回 {success: N, failed: M}
        """
        if not documents:
            return {"success": 0, "failed": 0}

        # 确保collection存在
        vector_size = get_vector_size(collection)
        ok = await QdrantClient.create_collection_if_not_exists(collection, vector_size)
        if not ok:
            logger.warning("batch_index_collection_unavailable", collection=collection)
            return {"success": 0, "failed": len(documents)}

        success_count = 0
        failed_count = 0

        # 分批处理
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]

            texts = [doc.get("text", "") for doc in batch]
            vectors = await EmbeddingService.embed_batch(texts)

            points = []
            for doc, vector in zip(batch, vectors):
                doc_id = doc.get("doc_id", str(uuid.uuid4()))
                metadata = doc.get("metadata", {})
                text = doc.get("text", "")

                payload: dict[str, Any] = {
                    "tenant_id": tenant_id,
                    "doc_id": doc_id,
                    "text": text[:500],
                    **metadata,
                }
                points.append({
                    "id": _doc_id_to_int(doc_id),
                    "vector": vector,
                    "payload": payload,
                })

            batch_ok = await QdrantClient.upsert(collection, points)
            if batch_ok:
                success_count += len(batch)
            else:
                failed_count += len(batch)

        logger.info(
            "batch_index_done",
            collection=collection,
            tenant_id=tenant_id,
            success=success_count,
            failed=failed_count,
        )
        return {"success": success_count, "failed": failed_count}

    # ── 检索 ─────────────────────────────────────────────────

    @staticmethod
    async def search(
        collection: str,
        query: str,
        tenant_id: str,
        top_k: int = 5,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """带tenant隔离的向量检索。

        步骤：
        1. 向量化query
        2. 构建带tenant_id过滤的Qdrant filter
        3. 向量搜索

        Qdrant不可用时返回[]，不抛异常。
        """
        if not query or not query.strip():
            return []

        # 向量化查询
        query_vector = await EmbeddingService.embed_text(query)

        # 构建Qdrant过滤器（tenant隔离 + 额外过滤条件）
        must_conditions: list[dict[str, Any]] = [
            {
                "key": "tenant_id",
                "match": {"value": tenant_id},
            }
        ]

        if filters:
            for key, value in filters.items():
                must_conditions.append({
                    "key": key,
                    "match": {"value": value},
                })

        qdrant_filter: dict[str, Any] = {"must": must_conditions}

        results = await QdrantClient.search(
            collection=collection,
            query_vector=query_vector,
            filter=qdrant_filter,
            limit=top_k,
        )

        # 格式化结果
        formatted = []
        for hit in results:
            formatted.append({
                "doc_id": hit.get("payload", {}).get("doc_id", ""),
                "score": hit.get("score", 0.0),
                "text": hit.get("payload", {}).get("text", ""),
                "metadata": {
                    k: v
                    for k, v in hit.get("payload", {}).items()
                    if k not in ("tenant_id", "text", "doc_id")
                },
            })

        return formatted

    # ── 业务专用索引方法 ────────────────────────────────────

    @staticmethod
    async def index_menu_knowledge(
        brand_id: str,
        tenant_id: str,
        db: Any,
    ) -> dict[str, int]:
        """将菜品信息从DB索引到menu_knowledge collection。

        从DB查询菜品数据，批量向量化写入Qdrant。
        db：SQLAlchemy AsyncSession（或兼容接口）
        """
        try:
            # 查询菜品数据（适配实际模型）
            from sqlalchemy import text as sql_text
            result = await db.execute(
                sql_text(
                    "SELECT id, name, description, category, price "
                    "FROM menu_items "
                    "WHERE brand_id = :brand_id AND is_active = true"
                ),
                {"brand_id": brand_id},
            )
            rows = result.fetchall()
        except Exception as exc:  # noqa: BLE001 — DB驱动异常类型多样
            logger.warning(
                "index_menu_knowledge_db_error",
                brand_id=brand_id,
                error=str(exc),
            )
            return {"success": 0, "failed": 0}

        documents = []
        for row in rows:
            item_id, name, description, category, price = (
                str(row[0]),
                row[1] or "",
                row[2] or "",
                row[3] or "",
                str(row[4]) if row[4] else "",
            )
            text = f"{name} {description}".strip()
            if not text:
                continue
            documents.append({
                "doc_id": f"menu:{brand_id}:{item_id}",
                "text": text,
                "metadata": {
                    "brand_id": brand_id,
                    "item_id": item_id,
                    "category": category,
                    "price": price,
                },
            })

        if not documents:
            logger.info("index_menu_knowledge_no_items", brand_id=brand_id)
            return {"success": 0, "failed": 0}

        return await KnowledgeRetrievalService.index_documents_batch(
            collection="menu_knowledge",
            documents=documents,
            tenant_id=tenant_id,
        )

    @staticmethod
    async def index_decision_history(
        agent_id: str,
        decision_log: dict[str, Any],
        tenant_id: str,
    ) -> bool:
        """将Agent决策日志索引到decision_history collection。

        decision_log字段：
        - decision_id: str
        - action: str
        - reasoning: str
        - outcome: str (accepted/rejected/rolled_back)
        - confidence: float
        - created_at: str
        """
        decision_id = decision_log.get("decision_id", str(uuid.uuid4()))
        action = decision_log.get("action", "")
        reasoning = decision_log.get("reasoning", "")
        outcome = decision_log.get("outcome", "")
        confidence = decision_log.get("confidence", 0.0)
        created_at = decision_log.get("created_at", "")

        # 索引文本：action + reasoning（用于语义检索相似历史决策）
        text = f"[{action}] {reasoning}".strip()
        if not text:
            return False

        doc_id = f"decision:{agent_id}:{decision_id}"
        metadata = {
            "agent_id": agent_id,
            "action": action,
            "outcome": outcome,
            "confidence": str(confidence),
            "created_at": created_at,
        }

        return await KnowledgeRetrievalService.index_document(
            collection="decision_history",
            doc_id=doc_id,
            text=text,
            metadata=metadata,
            tenant_id=tenant_id,
        )


# ── 工具函数 ─────────────────────────────────────────────────

def _doc_id_to_int(doc_id: str) -> int:
    """将字符串doc_id转换为Qdrant使用的整数ID（取MD5前16字节）"""
    digest = hashlib.md5(doc_id.encode()).hexdigest()
    return int(digest[:16], 16)
