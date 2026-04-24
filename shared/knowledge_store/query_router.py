"""查询路由器 — 根据查询复杂度自动选择检索策略

策略：
- Simple（关键词匹配即可）: 直接 hybrid_search(top_k)
- Medium（需要语义理解）: hybrid_search(top_20) → rerank(top_5)
- Complex（多步推理/比较）: 分解子问题 → 逐步检索 → 合并去重 → rerank
"""

from __future__ import annotations

import re
import time
from enum import Enum
from typing import Any

import structlog

from .hybrid_search import HybridSearchEngine
from .models import QueryResult
from .reranker import RerankerService

logger = structlog.get_logger()


class QueryComplexity(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


# 简单查询模式（关键词匹配即可）
_SIMPLE_PATTERNS = [
    r"^.{1,15}$",  # 很短的查询（<15字符）
    r"^(什么是|查看|显示|列出|打印)",  # 直接查询
    r"(SOP|操作规范|标准|流程)$",  # SOP查询
]

# 复杂查询模式（需要多步推理）
_COMPLEX_PATTERNS = [
    r"(为什么|原因|根因|分析)",  # 因果分析
    r"(比较|对比|区别|差异)",  # 比较分析
    r"(如何.*同时|既.*又)",  # 多条件
    r"(趋势|变化|历史)",  # 趋势分析
    r"(优化|改进|提升|降低).*方案",  # 方案推荐
]


class QueryRouter:
    """查询路由器 — 按复杂度选择检索策略"""

    @staticmethod
    def classify_query(query: str) -> QueryComplexity:
        """分类查询复杂度。

        基于规则快速分类，不调用 LLM（保持低延迟）。
        """
        if not query or not query.strip():
            return QueryComplexity.SIMPLE

        # 检查复杂模式
        for pattern in _COMPLEX_PATTERNS:
            if re.search(pattern, query):
                return QueryComplexity.COMPLEX

        # 检查简单模式
        for pattern in _SIMPLE_PATTERNS:
            if re.search(pattern, query):
                return QueryComplexity.SIMPLE

        # 默认中等复杂度
        return QueryComplexity.MEDIUM

    @staticmethod
    async def route_and_retrieve(
        query: str,
        collection: str,
        tenant_id: str,
        db: Any,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """根据查询复杂度路由到对应检索策略。

        Args:
            query: 检索查询
            collection: 知识集合
            tenant_id: 租户ID
            db: AsyncSession
            top_k: 返回数量
            filters: 额外过滤条件

        Returns:
            QueryResult 包含检索结果和元信息
        """
        start_time = time.monotonic()
        complexity = QueryRouter.classify_query(query)

        logger.info(
            "query_router_classified",
            query=query[:50],
            complexity=complexity.value,
        )

        if complexity == QueryComplexity.SIMPLE:
            results = await _simple_retrieve(query, collection, tenant_id, db, top_k, filters)
        elif complexity == QueryComplexity.MEDIUM:
            results = await _medium_retrieve(query, collection, tenant_id, db, top_k, filters)
        else:
            results = await _complex_retrieve(query, collection, tenant_id, db, top_k, filters)

        latency_ms = int((time.monotonic() - start_time) * 1000)

        return QueryResult(
            query=query,
            complexity=complexity.value,
            results=results,
            latency_ms=latency_ms,
        )

    @staticmethod
    def decompose_query(query: str) -> list[str]:
        """将复杂查询分解为子问题（基于规则，不调用 LLM）。

        例：
        "为什么A店翻台率下降而B店上升？"
        → ["A店翻台率是多少", "B店翻台率是多少", "翻台率下降的常见原因"]
        """
        sub_queries: list[str] = []

        # 比较类：拆分为各自查询
        compare_match = re.search(r"(.+)(比较|对比|区别)(.+)", query)
        if compare_match:
            sub_queries.append(compare_match.group(1).strip())
            sub_queries.append(compare_match.group(3).strip())
            return sub_queries if sub_queries else [query]

        # 因果类：拆分为现象 + 原因
        cause_match = re.search(r"为什么(.+)", query)
        if cause_match:
            phenomenon = cause_match.group(1).strip()
            sub_queries.append(phenomenon)
            sub_queries.append(f"{phenomenon}的原因")
            return sub_queries

        # 默认不分解
        return [query]


async def _simple_retrieve(
    query: str,
    collection: str,
    tenant_id: str,
    db: Any,
    top_k: int,
    filters: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """简单检索：直接 hybrid_search"""
    return await HybridSearchEngine.search(
        query=query,
        collection=collection,
        tenant_id=tenant_id,
        db=db,
        top_k=top_k,
        filters=filters,
    )


async def _medium_retrieve(
    query: str,
    collection: str,
    tenant_id: str,
    db: Any,
    top_k: int,
    filters: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """中等检索：hybrid_search(top_20) → rerank(top_k)"""
    candidates = await HybridSearchEngine.search(
        query=query,
        collection=collection,
        tenant_id=tenant_id,
        db=db,
        top_k=20,
        filters=filters,
    )
    if not candidates:
        return []

    return await RerankerService.rerank(query, candidates, top_k=top_k)


async def _complex_retrieve(
    query: str,
    collection: str,
    tenant_id: str,
    db: Any,
    top_k: int,
    filters: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """复杂检索：分解 → 逐步检索 → 合并去重 → rerank"""
    sub_queries = QueryRouter.decompose_query(query)

    all_results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for sq in sub_queries:
        sub_results = await HybridSearchEngine.search(
            query=sq,
            collection=collection,
            tenant_id=tenant_id,
            db=db,
            top_k=10,
            filters=filters,
        )
        for r in sub_results:
            key = r.get("chunk_id") or r.get("doc_id", "")
            if key not in seen_ids:
                seen_ids.add(key)
                all_results.append(r)

    if not all_results:
        return []

    # 对合并结果精排
    return await RerankerService.rerank(query, all_results, top_k=top_k)
