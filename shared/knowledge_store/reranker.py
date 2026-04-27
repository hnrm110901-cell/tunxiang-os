"""Voyage Rerank-2 精排服务

对粗召回结果（top-20）重排序，返回 top-5 高质量结果。
API 不可用时降级为分数阈值过滤。
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

_VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
_RERANK_URL = "https://api.voyageai.com/v1/rerank"
_TIMEOUT = 10.0
_FALLBACK_SCORE_THRESHOLD = 0.3


class RerankerService:
    """Voyage rerank-2 精排服务"""

    @staticmethod
    async def rerank(
        query: str,
        documents: list[dict[str, Any]],
        top_k: int = 5,
        model: str = "rerank-2",
    ) -> list[dict[str, Any]]:
        """对检索结果精排序。

        Args:
            query: 原始查询
            documents: 粗召回结果列表（需包含 text 字段）
            top_k: 返回精排后 top_k 条
            model: rerank 模型名称

        Returns:
            精排后的文档列表（保留原有字段 + 更新 score）
        """
        if not documents:
            return []

        if len(documents) <= top_k:
            return documents

        # 尝试 API 精排
        reranked = await _try_api_rerank(query, documents, top_k, model)
        if reranked is not None:
            return reranked

        # 降级：按原始分数过滤 + 截取
        logger.warning("rerank_api_unavailable_fallback", doc_count=len(documents))
        return _fallback_rerank(documents, top_k)


async def _try_api_rerank(
    query: str,
    documents: list[dict[str, Any]],
    top_k: int,
    model: str,
) -> list[dict[str, Any]] | None:
    """调用 Voyage rerank API"""
    if not _VOYAGE_API_KEY:
        return None

    try:
        texts = [doc.get("text", "") for doc in documents]

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _RERANK_URL,
                json={
                    "model": model,
                    "query": query,
                    "documents": texts,
                    "top_k": top_k,
                },
                headers={
                    "Authorization": f"Bearer {_VOYAGE_API_KEY}",
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code != 200:
                logger.warning("rerank_api_error", status=resp.status_code, body=resp.text[:200])
                return None

            data = resp.json()
            results = data.get("data", [])

            # 按 API 返回的排序重建文档列表
            reranked = []
            for item in results:
                idx = item.get("index", 0)
                if 0 <= idx < len(documents):
                    doc = {**documents[idx]}
                    doc["score"] = item.get("relevance_score", 0.0)
                    reranked.append(doc)

            logger.info("rerank_api_ok", input_count=len(documents), output_count=len(reranked))
            return reranked

    except Exception as exc:
        logger.warning("rerank_api_exception", error=str(exc), exc_info=True)
        return None


def _fallback_rerank(
    documents: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """降级精排：按原始分数排序 + 阈值过滤"""
    sorted_docs = sorted(documents, key=lambda d: d.get("score", 0.0), reverse=True)
    filtered = [d for d in sorted_docs if d.get("score", 0.0) >= _FALLBACK_SCORE_THRESHOLD]
    if not filtered:
        filtered = sorted_docs
    return filtered[:top_k]
