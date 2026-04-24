"""双层图谱检索器 -- LightRAG 风格

Low-level: 实体匹配 + 1-hop 关系遍历（具体事实查询）
High-level: 社区摘要匹配（主题/概述类查询）
Hybrid: 图谱检索 + 向量检索融合
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from shared.vector_store.embeddings import EmbeddingService

from .hybrid_search import HybridSearchEngine
from .pg_graph_repository import PgGraphRepository

logger = structlog.get_logger()


class GraphRetriever:
    """双层知识图谱检索器"""

    @staticmethod
    async def low_level_retrieve(
        query: str,
        tenant_id: str,
        db: Any,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """低层检索：实体匹配 + 关系遍历。

        适用于具体事实查询（如"剁椒鱼头用了什么食材"）。
        """
        # 1. 向量化查询
        query_embedding = await EmbeddingService.embed_text(query)

        # 2. 语义搜索匹配实体
        matched_nodes = await PgGraphRepository.search_nodes_by_embedding(
            embedding=query_embedding,
            tenant_id=tenant_id,
            db=db,
            top_k=5,
        )

        # 3. 名称模糊搜索补充
        name_matches = await PgGraphRepository.search_nodes_by_name(
            query=query[:20],  # 取前20字作为名称搜索
            tenant_id=tenant_id,
            db=db,
            top_k=5,
        )

        # 合并去重
        seen_ids: set[str] = set()
        all_nodes: list[dict[str, Any]] = []
        for node in matched_nodes + name_matches:
            if node["id"] not in seen_ids:
                seen_ids.add(node["id"])
                all_nodes.append(node)

        # 4. 获取邻居（1-hop 关系）
        results: list[dict[str, Any]] = []
        for node in all_nodes[:5]:  # 最多扩展5个节点
            neighbors = await PgGraphRepository.get_neighbors(
                node_id=node["id"],
                tenant_id=tenant_id,
                db=db,
            )
            # 将节点和邻居组织为检索结果
            context = _format_node_context(node, neighbors)
            results.append(
                {
                    "doc_id": f"kg:{node['id']}",
                    "chunk_id": f"kg:{node['id']}",
                    "text": context,
                    "score": node.get("score", 0.5),
                    "metadata": {
                        "source": "knowledge_graph",
                        "node_label": node.get("label", ""),
                        "node_name": node.get("name", ""),
                        "neighbor_count": len(neighbors),
                    },
                }
            )

        return results[:top_k]

    @staticmethod
    async def high_level_retrieve(
        query: str,
        tenant_id: str,
        db: Any,
    ) -> list[dict[str, Any]]:
        """高层检索：社区摘要匹配。

        适用于主题概述类查询（如"食品安全有哪些要求"）。
        """
        communities = await PgGraphRepository.list_communities(tenant_id, db)

        results: list[dict[str, Any]] = []
        for comm in communities:
            summary = comm.get("summary", "")
            if not summary:
                continue

            # 简单相关度：查询关键字与社区摘要的重叠
            relevance = _compute_text_relevance(query, summary)
            if relevance > 0.1:
                results.append(
                    {
                        "doc_id": f"community:{comm['id']}",
                        "chunk_id": f"community:{comm['id']}",
                        "text": summary,
                        "score": relevance,
                        "metadata": {
                            "source": "community_summary",
                            "community_label": comm.get("label", ""),
                            "node_count": comm.get("node_count", 0),
                        },
                    }
                )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:5]

    @staticmethod
    async def hybrid_graph_retrieve(
        query: str,
        collection: str,
        tenant_id: str,
        db: Any,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """混合图谱检索：低层 + 高层 + 向量检索融合"""

        # 三路并行检索
        low_results, high_results, vector_results = await asyncio.gather(
            GraphRetriever.low_level_retrieve(query, tenant_id, db, top_k=10),
            GraphRetriever.high_level_retrieve(query, tenant_id, db),
            HybridSearchEngine.search(
                query=query,
                collection=collection,
                tenant_id=tenant_id,
                db=db,
                top_k=10,
            ),
        )

        # 合并去重
        seen_ids: set[str] = set()
        merged: list[dict[str, Any]] = []

        # 向量结果优先（通常更精准）
        for r in vector_results:
            key = r.get("chunk_id") or r.get("doc_id", "")
            if key not in seen_ids:
                seen_ids.add(key)
                merged.append(r)

        # 图谱低层结果
        for r in low_results:
            key = r.get("chunk_id") or r.get("doc_id", "")
            if key not in seen_ids:
                seen_ids.add(key)
                r["score"] = r.get("score", 0.0) * 0.8  # 图谱结果略微降权
                merged.append(r)

        # 社区高层结果
        for r in high_results:
            key = r.get("chunk_id") or r.get("doc_id", "")
            if key not in seen_ids:
                seen_ids.add(key)
                r["score"] = r.get("score", 0.0) * 0.6  # 社区摘要权重更低
                merged.append(r)

        merged.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        logger.info(
            "hybrid_graph_retrieve_done",
            vector_hits=len(vector_results),
            low_level_hits=len(low_results),
            high_level_hits=len(high_results),
            merged_total=len(merged),
        )

        return merged[:top_k]


def _format_node_context(node: dict[str, Any], neighbors: list[dict[str, Any]]) -> str:
    """将节点及邻居格式化为可读文本"""
    parts = [f"{node.get('label', '')}：{node.get('name', '')}"]

    props = node.get("properties", {})
    if props:
        for k, v in list(props.items())[:5]:
            parts.append(f"  {k}: {v}")

    for n in neighbors[:10]:
        rel = n.get("rel_type", "")
        name = n.get("name", "")
        label = n.get("label", "")
        parts.append(f"  -> [{rel}] {label}:{name}")

    return "\n".join(parts)


def _compute_text_relevance(query: str, text: str) -> float:
    """简单文本相关度（字符重叠率）"""
    if not query or not text:
        return 0.0
    query_chars = set(c for c in query if "\u4e00" <= c <= "\u9fff")
    text_chars = set(c for c in text[:500] if "\u4e00" <= c <= "\u9fff")
    if not query_chars:
        return 0.3
    return len(query_chars & text_chars) / len(query_chars)
