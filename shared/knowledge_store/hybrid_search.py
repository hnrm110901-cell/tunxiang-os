"""混合检索引擎 — 向量 + 关键词 + RRF 融合排序

Reciprocal Rank Fusion (RRF):
  score(d) = Σ(1 / (k + rank_i(d)))  where k = 60

两路检索分别取 top-20，RRF 融合后返回 top-k。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from shared.vector_store.embeddings import EmbeddingService

from .pg_vector_store import PgVectorStore

logger = structlog.get_logger()

# RRF 常数 k（论文推荐值 60）
_RRF_K = 60


class HybridSearchEngine:
    """混合检索引擎（向量 + 关键词 + RRF 融合）"""

    @staticmethod
    async def search(
        query: str,
        collection: str,
        tenant_id: str,
        db: Any,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
        retrieval_k: int = 20,
    ) -> list[dict[str, Any]]:
        """混合检索：向量 + 关键词 → RRF 融合 → top_k。

        Args:
            query: 检索查询
            collection: 知识集合名称
            tenant_id: 租户ID
            db: SQLAlchemy AsyncSession
            top_k: 返回结果数
            filters: 额外元数据过滤条件
            vector_weight: 向量检索权重（RRF 融合时使用）
            keyword_weight: 关键词检索权重
            retrieval_k: 每路检索的候选数

        Returns:
            [{chunk_id, doc_id, text, score, metadata, chunk_index, document_id}]
        """
        if not query or not query.strip():
            return []

        # 1. 向量化查询
        query_embedding = await EmbeddingService.embed_text(query)

        # 2. 双路检索（并行执行）
        vector_results, keyword_results = await asyncio.gather(
            PgVectorStore.vector_search(
                query_embedding=query_embedding,
                collection=collection,
                tenant_id=tenant_id,
                db=db,
                top_k=retrieval_k,
                filters=filters,
            ),
            PgVectorStore.keyword_search(
                query=query,
                collection=collection,
                tenant_id=tenant_id,
                db=db,
                top_k=retrieval_k,
                filters=filters,
            ),
        )

        # 3. RRF 融合
        fused = _rrf_fuse(
            vector_results=vector_results,
            keyword_results=keyword_results,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )

        # 4. 截取 top_k
        fused.sort(key=lambda x: x["score"], reverse=True)

        logger.info(
            "hybrid_search_done",
            collection=collection,
            vector_hits=len(vector_results),
            keyword_hits=len(keyword_results),
            fused_total=len(fused),
            returned=min(len(fused), top_k),
        )

        return fused[:top_k]


def _rrf_fuse(
    vector_results: list[dict[str, Any]],
    keyword_results: list[dict[str, Any]],
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> list[dict[str, Any]]:
    """RRF (Reciprocal Rank Fusion) 融合两路检索结果。

    score(d) = w_v * (1 / (k + rank_v(d))) + w_k * (1 / (k + rank_k(d)))
    """
    # 以 chunk_id 或 doc_id 为 key 合并
    merged: dict[str, dict[str, Any]] = {}

    # 向量检索结果
    for rank, item in enumerate(vector_results):
        key = item.get("chunk_id") or item.get("doc_id", "")
        rrf_score = vector_weight * (1.0 / (_RRF_K + rank + 1))

        if key in merged:
            merged[key]["score"] += rrf_score
        else:
            merged[key] = {**item, "score": rrf_score}

    # 关键词检索结果
    for rank, item in enumerate(keyword_results):
        key = item.get("chunk_id") or item.get("doc_id", "")
        rrf_score = keyword_weight * (1.0 / (_RRF_K + rank + 1))

        if key in merged:
            merged[key]["score"] += rrf_score
        else:
            merged[key] = {**item, "score": rrf_score}

    return list(merged.values())
