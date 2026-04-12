"""纠错式 RAG — 检测检索质量，必要时重写查询重试

流程：
1. 执行检索
2. 评估最高相关度分数
3. 如果 < 阈值(0.6)：改写查询 → 重新检索（最多重试2次）
4. 返回最佳结果
"""
from __future__ import annotations

import re
from typing import Any

import structlog

from .hybrid_search import HybridSearchEngine
from .reranker import RerankerService

logger = structlog.get_logger()

_RELEVANCE_THRESHOLD = 0.6
_MAX_RETRIES = 2


class CorrectiveRAG:
    """纠错式检索增强"""

    @staticmethod
    async def retrieve_with_correction(
        query: str,
        collection: str,
        tenant_id: str,
        db: Any,
        top_k: int = 5,
    ) -> tuple[list[dict[str, Any]], int]:
        """带纠错的检索。

        Returns:
            (results, rewrite_count) — 检索结果和查询改写次数
        """
        current_query = query
        rewrite_count = 0

        for attempt in range(1 + _MAX_RETRIES):
            # 检索
            candidates = await HybridSearchEngine.search(
                query=current_query,
                collection=collection,
                tenant_id=tenant_id,
                db=db,
                top_k=20,
            )

            if not candidates:
                if attempt < _MAX_RETRIES:
                    current_query = _rewrite_query(query, current_query, [])
                    rewrite_count += 1
                    continue
                return [], rewrite_count

            # 精排
            reranked = await RerankerService.rerank(current_query, candidates, top_k=top_k)

            # 检查最高相关度
            max_score = max((r.get("score", 0.0) for r in reranked), default=0.0)

            if max_score >= _RELEVANCE_THRESHOLD or attempt >= _MAX_RETRIES:
                logger.info(
                    "corrective_rag_done",
                    query=query[:50],
                    final_query=current_query[:50] if current_query != query else None,
                    max_score=max_score,
                    rewrite_count=rewrite_count,
                    attempt=attempt + 1,
                )
                return reranked, rewrite_count

            # 相关度不足，改写查询
            current_query = _rewrite_query(query, current_query, reranked)
            rewrite_count += 1

            logger.info(
                "corrective_rag_rewrite",
                original=query[:50],
                rewritten=current_query[:50],
                max_score=max_score,
                attempt=attempt + 1,
            )

        return [], rewrite_count


def _rewrite_query(
    original_query: str,
    current_query: str,
    failed_results: list[dict[str, Any]],
) -> str:
    """基于规则改写查询（不调用 LLM，保持低延迟）。

    策略：
    1. 去除过于具体的限定词
    2. 扩展同义词
    3. 简化为核心关键词
    """
    # 提取失败结果中的高频词作为反馈
    irrelevant_words = set()
    for r in failed_results[:3]:
        text = r.get("text", "")
        # 简单提取：取文本前20字
        irrelevant_words.update(text[:20].split())

    # 策略1：去除过于具体的修饰词
    simplified = re.sub(r"(具体|详细|完整|全部|所有|最新)", "", original_query)

    # 策略2：中文同义词扩展
    synonyms = {
        "毛利": "利润 毛利率",
        "翻台率": "翻台 周转",
        "客单价": "客单 均价",
        "食安": "食品安全 卫生",
        "SOP": "操作规范 标准流程",
        "排班": "班次 工时",
    }
    expanded = simplified
    for key, expansion in synonyms.items():
        if key in expanded:
            expanded = f"{expanded} {expansion}"
            break

    rewritten = expanded.strip()
    return rewritten if rewritten else original_query


def score_relevance_simple(query: str, text: str) -> float:
    """简单的相关度评分（基于关键词重叠率）。

    用于无 LLM 环境下的粗略评估。
    """
    if not query or not text:
        return 0.0

    query_chars = set(query.lower())
    text_chars = set(text[:200].lower())

    # 中文字符重叠
    chinese_q = {c for c in query_chars if "\u4e00" <= c <= "\u9fff"}
    chinese_t = {c for c in text_chars if "\u4e00" <= c <= "\u9fff"}

    if not chinese_q:
        return 0.5  # 无中文字符时给默认中等分

    overlap = len(chinese_q & chinese_t)
    return min(overlap / len(chinese_q), 1.0)
