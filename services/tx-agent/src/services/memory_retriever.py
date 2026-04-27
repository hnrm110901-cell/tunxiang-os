"""MemoryRetriever — 多路检索 + RRF 融合引擎

参考 Mem0 检索架构：向量语义 + 全文关键词 + 分类匹配三路并行，
通过 Reciprocal Rank Fusion 融合排序，叠加时间衰减和作用域优先级。

被 MemoryEvolutionService.recall() 组合调用，不对外直接暴露。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent_memory import AgentMemory

logger = structlog.get_logger(__name__)

# RRF 标准常数
_RRF_K = 60


class MemoryRetriever:
    """多路检索 + RRF 融合 — 参考 Mem0 检索架构"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── 公开入口 ────────────────────────────────────────────────

    async def hybrid_search(
        self,
        tenant_id: str,
        store_id: str | None,
        user_id: str | None,
        query: str,
        embedding: list[float] | None = None,
        *,
        top_k: int = 10,
        memory_types: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> list[dict]:
        """混合检索入口

        Returns:
            按融合分数降序排列的记忆 dict 列表，每项包含
            id / memory_key / content / score / scope / memory_type 等字段
        """
        result_sets: list[tuple[str, list[dict], float]] = []

        # 1. 向量语义搜索（需要 embedding）
        if embedding:
            vector_results = await self._vector_search(
                tenant_id,
                store_id,
                user_id,
                embedding,
                memory_types=memory_types,
                limit=top_k * 2,
            )
            result_sets.append(("vector", vector_results, 0.5))

        # 2. 全文关键词搜索
        text_results = await self._text_search(
            tenant_id,
            store_id,
            user_id,
            query,
            memory_types=memory_types,
            limit=top_k * 2,
        )
        result_sets.append(("text", text_results, 0.3))

        # 3. 精确分类匹配
        if categories:
            cat_results = await self._category_match(
                tenant_id,
                store_id,
                user_id,
                categories,
                memory_types=memory_types,
                limit=top_k * 2,
            )
            result_sets.append(("category", cat_results, 0.2))

        # 4. RRF 融合
        fused = self._reciprocal_rank_fusion(result_sets)

        # 5. 时间衰减加权
        fused = self._apply_time_decay(fused)

        # 6. 作用域优先级排序
        fused = self._apply_scope_priority(fused, user_id, store_id)

        # 7. 按最终分数降序排列
        fused.sort(key=lambda r: r.get("score", 0), reverse=True)

        logger.debug(
            "hybrid_search_done",
            tenant_id=tenant_id,
            query_len=len(query),
            channels=len(result_sets),
            total_fused=len(fused),
            returned=min(top_k, len(fused)),
        )
        return fused[:top_k]

    # ── 向量语义搜索 ────────────────────────────────────────────

    async def _vector_search(
        self,
        tenant_id: str,
        store_id: str | None,
        user_id: str | None,
        query_embedding: list[float],
        *,
        memory_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """pgvector cosine similarity 搜索

        使用 1 - (embedding <=> :query_embedding) 计算余弦相似度，
        仅搜索 embedding IS NOT NULL 且未失效的记忆。
        """
        now = datetime.now(timezone.utc)
        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        # 构建 WHERE 子句
        conditions = [
            "tenant_id = :tenant_id",
            "is_deleted = FALSE",
            "embedding IS NOT NULL",
            "(valid_until IS NULL OR valid_until > :now)",
        ]
        params: dict = {
            "tenant_id": UUID(tenant_id),
            "query_embedding": embedding_str,
            "now": now,
            "limit": limit,
        }

        if store_id:
            conditions.append("(store_id = :store_id OR store_id IS NULL)")
            params["store_id"] = UUID(store_id)
        if user_id:
            conditions.append("(user_id = :user_id OR user_id IS NULL)")
            params["user_id"] = UUID(user_id)
        if memory_types:
            conditions.append("memory_type = ANY(:memory_types)")
            params["memory_types"] = memory_types

        where_clause = " AND ".join(conditions)

        sql = text(f"""
            SELECT id, memory_type, memory_key, content, confidence,
                   store_id, user_id, scope, category, importance,
                   updated_at, access_count,
                   1 - (embedding <=> :query_embedding::vector) AS similarity
            FROM agent_memories
            WHERE {where_clause}
            ORDER BY similarity DESC
            LIMIT :limit
        """)

        result = await self.db.execute(sql, params)
        rows = result.mappings().all()

        return [
            {
                "id": str(row["id"]),
                "memory_type": row["memory_type"],
                "memory_key": row["memory_key"],
                "content": row["content"],
                "confidence": row["confidence"],
                "store_id": str(row["store_id"]) if row["store_id"] else None,
                "user_id": str(row["user_id"]) if row["user_id"] else None,
                "scope": row["scope"],
                "category": row["category"],
                "importance": row["importance"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "access_count": row["access_count"],
                "similarity": float(row["similarity"]),
                "source": "vector",
            }
            for row in rows
        ]

    # ── 全文关键词搜索 ──────────────────────────────────────────

    async def _text_search(
        self,
        tenant_id: str,
        store_id: str | None,
        user_id: str | None,
        query: str,
        *,
        memory_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """ILIKE 文本搜索（memory_key + content::text）"""
        now = datetime.now(timezone.utc)
        # 转义 LIKE 通配符
        safe_query = query.replace("%", r"\%").replace("_", r"\_")

        stmt = (
            select(AgentMemory)
            .where(
                AgentMemory.tenant_id == UUID(tenant_id),
                AgentMemory.is_deleted == False,  # noqa: E712
                (AgentMemory.valid_until.is_(None)) | (AgentMemory.valid_until > now),
            )
            .where(AgentMemory.memory_key.ilike(f"%{safe_query}%"))
        )

        if store_id:
            stmt = stmt.where((AgentMemory.store_id == UUID(store_id)) | (AgentMemory.store_id.is_(None)))
        if user_id:
            stmt = stmt.where((AgentMemory.user_id == UUID(user_id)) | (AgentMemory.user_id.is_(None)))
        if memory_types:
            stmt = stmt.where(AgentMemory.memory_type.in_(memory_types))

        stmt = stmt.order_by(AgentMemory.importance.desc()).limit(limit)
        result = await self.db.execute(stmt)
        memories = result.scalars().all()

        return [
            {
                "id": str(m.id),
                "memory_type": m.memory_type,
                "memory_key": m.memory_key,
                "content": m.content,
                "confidence": m.confidence,
                "store_id": str(m.store_id) if m.store_id else None,
                "user_id": str(m.user_id) if m.user_id else None,
                "scope": m.scope,
                "category": m.category,
                "importance": m.importance,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                "access_count": m.access_count,
                "similarity": 0.0,
                "source": "text",
            }
            for m in memories
        ]

    # ── 精确分类匹配 ────────────────────────────────────────────

    async def _category_match(
        self,
        tenant_id: str,
        store_id: str | None,
        user_id: str | None,
        categories: list[str],
        *,
        memory_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """按 category 精确匹配"""
        now = datetime.now(timezone.utc)

        stmt = select(AgentMemory).where(
            AgentMemory.tenant_id == UUID(tenant_id),
            AgentMemory.is_deleted == False,  # noqa: E712
            (AgentMemory.valid_until.is_(None)) | (AgentMemory.valid_until > now),
            AgentMemory.category.in_(categories),
        )

        if store_id:
            stmt = stmt.where((AgentMemory.store_id == UUID(store_id)) | (AgentMemory.store_id.is_(None)))
        if user_id:
            stmt = stmt.where((AgentMemory.user_id == UUID(user_id)) | (AgentMemory.user_id.is_(None)))
        if memory_types:
            stmt = stmt.where(AgentMemory.memory_type.in_(memory_types))

        stmt = stmt.order_by(AgentMemory.importance.desc()).limit(limit)
        result = await self.db.execute(stmt)
        memories = result.scalars().all()

        return [
            {
                "id": str(m.id),
                "memory_type": m.memory_type,
                "memory_key": m.memory_key,
                "content": m.content,
                "confidence": m.confidence,
                "store_id": str(m.store_id) if m.store_id else None,
                "user_id": str(m.user_id) if m.user_id else None,
                "scope": m.scope,
                "category": m.category,
                "importance": m.importance,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                "access_count": m.access_count,
                "similarity": 0.0,
                "source": "category",
            }
            for m in memories
        ]

    # ── RRF 融合排序 ────────────────────────────────────────────

    def _reciprocal_rank_fusion(
        self,
        result_sets: list[tuple[str, list[dict], float]],
    ) -> list[dict]:
        """Reciprocal Rank Fusion 融合排序

        score = sum(weight / (k + rank)) for each result set
        k = 60 (standard RRF constant)
        """
        scored: dict[str, dict] = {}  # memory_id -> merged dict

        for _channel, results, weight in result_sets:
            for rank, item in enumerate(results):
                mid = item["id"]
                rrf_score = weight / (_RRF_K + rank + 1)

                if mid in scored:
                    scored[mid]["score"] += rrf_score
                else:
                    scored[mid] = {**item, "score": rrf_score}

        return list(scored.values())

    # ── 时间衰减 ────────────────────────────────────────────────

    def _apply_time_decay(self, results: list[dict]) -> list[dict]:
        """时间衰减: score *= e^(-0.01 * days_since_update)

        距离上次更新越久，分数越低。最大衰减至 0.1x。
        """
        now = datetime.now(timezone.utc)

        for item in results:
            updated_str = item.get("updated_at")
            if updated_str:
                try:
                    updated_at = datetime.fromisoformat(updated_str)
                    days = (now - updated_at).total_seconds() / 86400.0
                    decay = max(math.exp(-0.01 * days), 0.1)
                    item["score"] = item.get("score", 0) * decay
                except (ValueError, TypeError):
                    pass  # 无法解析日期时不衰减

        return results

    # ── 作用域优先级 ────────────────────────────────────────────

    def _apply_scope_priority(
        self,
        results: list[dict],
        user_id: str | None,
        store_id: str | None,
    ) -> list[dict]:
        """作用域优先级加权

        user scope  -> x1.5（精准匹配用户的记忆最优先）
        store scope -> x1.2（门店级记忆次之）
        tenant scope -> x1.0（品牌级记忆基准）
        """
        for item in results:
            multiplier = 1.0
            item_user = item.get("user_id")
            item_store = item.get("store_id")

            if user_id and item_user and item_user == user_id:
                multiplier = 1.5
            elif store_id and item_store and item_store == store_id:
                multiplier = 1.2

            item["score"] = item.get("score", 0) * multiplier

        return results
