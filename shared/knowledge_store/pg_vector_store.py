"""pgvector 向量存储 — 替代 Qdrant 的 PostgreSQL 原生方案

基于 pgvector 扩展实现：
- 向量相似度检索（Cosine distance）
- 关键词全文检索（tsvector + GIN）
- 租户隔离（RLS + app.tenant_id）
- 优雅降级（数据库不可用时返回空结果）
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import text as sql_text

logger = structlog.get_logger()


async def _set_rls(db: Any, tenant_id: str) -> None:
    """设置 RLS 租户上下文"""
    await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


class PgVectorStore:
    """pgvector 向量存储引擎"""

    @staticmethod
    async def health_check(db: Any) -> bool:
        """检查 pgvector 扩展是否可用"""
        try:
            result = await db.execute(sql_text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            return result.scalar() is not None
        except Exception:
            return False  # health_check: 静默降级

    @staticmethod
    async def upsert_chunks(
        chunks: list[dict[str, Any]],
        tenant_id: str,
        db: Any,
    ) -> dict[str, int]:
        """批量写入知识块（含向量）。

        chunks 格式: [{text, embedding, metadata, doc_id, document_id, collection, chunk_index, token_count}]
        返回 {success: N, failed: M}
        """
        if not chunks:
            return {"success": 0, "failed": 0}

        success = 0
        failed = 0

        try:
            await _set_rls(db, tenant_id)

            for chunk in chunks:
                try:
                    chunk_id = str(uuid4())
                    embedding = chunk.get("embedding", [])
                    embedding_str = f"[{','.join(str(x) for x in embedding)}]" if embedding else None

                    await db.execute(
                        sql_text("""
                        INSERT INTO knowledge_chunks (
                            id, tenant_id, document_id, collection, doc_id,
                            chunk_index, text, embedding, token_count, metadata
                        ) VALUES (
                            :id, :tenant_id::uuid, :document_id::uuid, :collection, :doc_id,
                            :chunk_index, :text, :embedding::vector, :token_count, :metadata::jsonb
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            text = EXCLUDED.text,
                            embedding = EXCLUDED.embedding,
                            token_count = EXCLUDED.token_count,
                            metadata = EXCLUDED.metadata,
                            updated_at = NOW()
                    """),
                        {
                            "id": chunk_id,
                            "tenant_id": tenant_id,
                            "document_id": chunk.get("document_id", str(uuid4())),
                            "collection": chunk.get("collection", "ops_procedures"),
                            "doc_id": chunk.get("doc_id", ""),
                            "chunk_index": chunk.get("chunk_index", 0),
                            "text": chunk.get("text", ""),
                            "embedding": embedding_str,
                            "token_count": chunk.get("token_count", 0),
                            "metadata": _json_dumps(chunk.get("metadata", {})),
                        },
                    )
                    success += 1
                except Exception as exc:
                    logger.warning("upsert_chunk_failed", error=str(exc), doc_id=chunk.get("doc_id"), exc_info=True)
                    failed += 1

            await db.commit()

        except Exception as exc:
            logger.warning("upsert_chunks_batch_failed", error=str(exc), exc_info=True)
            failed = len(chunks) - success

        return {"success": success, "failed": failed}

    @staticmethod
    async def vector_search(
        query_embedding: list[float],
        collection: str,
        tenant_id: str,
        db: Any,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """向量相似度检索（Cosine distance）。

        返回 [{chunk_id, doc_id, text, score, metadata, chunk_index, document_id}]
        """
        try:
            await _set_rls(db, tenant_id)

            embedding_str = f"[{','.join(str(x) for x in query_embedding)}]"

            # 基础查询：cosine 相似度 = 1 - cosine_distance
            where_clauses = [
                "collection = :collection",
                "tenant_id = :tenant_id::uuid",
                "embedding IS NOT NULL",
                "is_deleted = false",
            ]
            params: dict[str, Any] = {
                "collection": collection,
                "tenant_id": tenant_id,
                "embedding": embedding_str,
                "top_k": top_k,
            }

            # 额外过滤条件（metadata jsonb）
            if filters:
                for i, (key, value) in enumerate(filters.items()):
                    where_clauses.append(f"metadata->>:fk{i} = :fv{i}")
                    params[f"fk{i}"] = key
                    params[f"fv{i}"] = str(value)

            where_sql = " AND ".join(where_clauses)

            result = await db.execute(
                sql_text(f"""
                SELECT
                    id::text AS chunk_id,
                    doc_id,
                    text,
                    1 - (embedding <=> :embedding::vector) AS score,
                    metadata,
                    chunk_index,
                    document_id::text
                FROM knowledge_chunks
                WHERE {where_sql}
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
            """),
                params,
            )

            rows = result.fetchall()
            return [
                {
                    "chunk_id": row[0],
                    "doc_id": row[1],
                    "text": row[2],
                    "score": float(row[3]) if row[3] else 0.0,
                    "metadata": row[4] if isinstance(row[4], dict) else {},
                    "chunk_index": row[5],
                    "document_id": row[6],
                }
                for row in rows
            ]

        except Exception as exc:
            logger.warning("vector_search_failed", error=str(exc), collection=collection, exc_info=True)
            return []

    @staticmethod
    async def keyword_search(
        query: str,
        collection: str,
        tenant_id: str,
        db: Any,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """关键词全文检索（tsvector + ts_rank）。

        返回格式与 vector_search 一致。
        """
        if not query or not query.strip():
            return []

        try:
            await _set_rls(db, tenant_id)

            where_clauses = [
                "collection = :collection",
                "tenant_id = :tenant_id::uuid",
                "is_deleted = false",
                "tsv @@ plainto_tsquery('simple', :query)",
            ]
            params: dict[str, Any] = {
                "collection": collection,
                "tenant_id": tenant_id,
                "query": query,
                "top_k": top_k,
            }

            if filters:
                for i, (key, value) in enumerate(filters.items()):
                    where_clauses.append(f"metadata->>:fk{i} = :fv{i}")
                    params[f"fk{i}"] = key
                    params[f"fv{i}"] = str(value)

            where_sql = " AND ".join(where_clauses)

            result = await db.execute(
                sql_text(f"""
                SELECT
                    id::text AS chunk_id,
                    doc_id,
                    text,
                    ts_rank(tsv, plainto_tsquery('simple', :query)) AS score,
                    metadata,
                    chunk_index,
                    document_id::text
                FROM knowledge_chunks
                WHERE {where_sql}
                ORDER BY score DESC
                LIMIT :top_k
            """),
                params,
            )

            rows = result.fetchall()
            return [
                {
                    "chunk_id": row[0],
                    "doc_id": row[1],
                    "text": row[2],
                    "score": float(row[3]) if row[3] else 0.0,
                    "metadata": row[4] if isinstance(row[4], dict) else {},
                    "chunk_index": row[5],
                    "document_id": row[6],
                }
                for row in rows
            ]

        except Exception as exc:
            logger.warning("keyword_search_failed", error=str(exc), collection=collection, exc_info=True)
            return []

    @staticmethod
    async def delete_by_document(
        document_id: str,
        tenant_id: str,
        db: Any,
    ) -> int:
        """删除指定文档的所有知识块"""
        try:
            await _set_rls(db, tenant_id)

            result = await db.execute(
                sql_text("""
                DELETE FROM knowledge_chunks
                WHERE document_id = :document_id::uuid
                AND tenant_id = :tenant_id::uuid
            """),
                {"document_id": document_id, "tenant_id": tenant_id},
            )

            await db.commit()
            return result.rowcount or 0

        except Exception as exc:
            logger.warning("delete_by_document_failed", error=str(exc), exc_info=True)
            return 0

    @staticmethod
    async def delete_by_doc_id(
        doc_id: str,
        collection: str,
        tenant_id: str,
        db: Any,
    ) -> int:
        """按 doc_id 删除知识块（向后兼容 Qdrant 模式）"""
        try:
            await _set_rls(db, tenant_id)

            result = await db.execute(
                sql_text("""
                DELETE FROM knowledge_chunks
                WHERE doc_id = :doc_id
                AND collection = :collection
                AND tenant_id = :tenant_id::uuid
            """),
                {"doc_id": doc_id, "collection": collection, "tenant_id": tenant_id},
            )

            await db.commit()
            return result.rowcount or 0

        except Exception as exc:
            logger.warning("delete_by_doc_id_failed", error=str(exc), exc_info=True)
            return 0


def _json_dumps(obj: Any) -> str:
    """安全的 JSON 序列化"""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "{}"
