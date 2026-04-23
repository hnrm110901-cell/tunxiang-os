"""MemoryEvolutionService — Agent 记忆进化服务

参考 Mem0 双阶段模型（提取 + 检索）+ Zep 时序管理。
不替换现有 AgentMemoryService，而是新增独立的进化版服务。

四类记忆：
- 长期语义记忆(agent_memories): 用户偏好/门店特征/学到的知识
- 情景记忆(agent_episodes): 过去的事件和决策
- 过程性记忆(agent_procedures): 学到的规则/策略
- 记忆审计(agent_memory_history): 变更日志
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime, timezone
from uuid import UUID

import httpx
import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent_episode import AgentEpisode
from ..models.agent_memory import AgentMemory
from ..models.agent_memory_history import AgentMemoryHistory
from ..models.agent_procedure import AgentProcedure
from .memory_retriever import MemoryRetriever

logger = structlog.get_logger(__name__)

# embedding 配置（优雅降级：不可用时退化为纯文本搜索）
_EMBEDDING_API_URL = os.getenv("EMBEDDING_API_URL", "")
_EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
_EMBEDDING_TIMEOUT = 10.0

# 相似度阈值 — cosine similarity > 此值视为"相似记忆"
_SIMILARITY_THRESHOLD = 0.85

# 衰减系数
_DECAY_LAMBDA = 0.01
_DECAY_FLOOR = 0.1


class MemoryEvolutionService:
    """Agent 记忆进化服务 — Mem0 双阶段 + Zep 时序管理"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._retriever = MemoryRetriever(db)

    # ══════════════════════════════════════════════════════════════
    # 长期语义记忆
    # ══════════════════════════════════════════════════════════════

    async def remember(
        self,
        tenant_id: str,
        store_id: str | None,
        user_id: str | None,
        content: str,
        memory_type: str,
        category: str,
        *,
        agent_id: str = "chief",
        source_event: str | None = None,
        importance: float = 0.5,
    ) -> AgentMemory:
        """提取阶段：创建或更新一条记忆

        1. 生成 embedding
        2. 搜索相似记忆（cosine > 0.85）
        3. 若相似 -> UPDATE（时序失效旧记忆，创建新版本）
        4. 若无相似 -> ADD 新记忆
        5. 写入 memory_history 审计
        """
        embedding = await self._generate_embedding(content)

        # 搜索相似记忆
        existing = await self._find_similar_memory(
            tenant_id, store_id, user_id, embedding, content,
            memory_type=memory_type,
        )

        now = datetime.now(timezone.utc)

        if existing:
            # UPDATE：时序失效旧记忆，创建新版本
            old_snapshot = {
                "memory_key": existing.memory_key,
                "content": existing.content,
                "confidence": existing.confidence,
                "importance": existing.importance,
            }

            # 标记旧版本失效
            existing.valid_until = now
            existing.is_deleted = True
            await self.db.flush()

            # 创建新版本
            memory = await self._create_memory(
                tenant_id=tenant_id,
                store_id=store_id,
                user_id=user_id,
                agent_id=agent_id,
                memory_type=memory_type,
                memory_key=content[:200],
                content={"text": content, "supersedes": str(existing.id)},
                category=category,
                embedding=embedding,
                importance=max(importance, existing.importance),
                source_event=source_event,
                access_count=existing.access_count,
            )

            new_snapshot = {
                "memory_key": memory.memory_key,
                "content": memory.content,
                "confidence": memory.confidence,
                "importance": memory.importance,
            }

            await self._log_history(
                tenant_id, str(existing.id), "agent_memories",
                "UPDATE", old_snapshot, new_snapshot,
                reason=f"superseded by {memory.id}",
            )

            logger.info(
                "memory_updated",
                old_id=str(existing.id),
                new_id=str(memory.id),
                memory_type=memory_type,
            )
            return memory

        # ADD：创建全新记忆
        memory = await self._create_memory(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            agent_id=agent_id,
            memory_type=memory_type,
            memory_key=content[:200],
            content={"text": content},
            category=category,
            embedding=embedding,
            importance=importance,
            source_event=source_event,
        )

        await self._log_history(
            tenant_id, str(memory.id), "agent_memories",
            "ADD", None,
            {"memory_key": memory.memory_key, "content": memory.content},
            reason="new memory created",
        )

        logger.info(
            "memory_created",
            memory_id=str(memory.id),
            memory_type=memory_type,
            category=category,
        )
        return memory

    async def recall(
        self,
        tenant_id: str,
        store_id: str | None,
        user_id: str | None,
        query: str,
        *,
        top_k: int = 10,
        memory_types: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> list[dict]:
        """检索阶段：混合检索 + 自动递增 access_count

        1. 向量语义搜索 + 全文关键词搜索 + 分类匹配
        2. RRF 融合 + 时间衰减 + 作用域排序
        3. 自动递增 access_count
        """
        embedding = await self._generate_embedding(query)

        results = await self._retriever.hybrid_search(
            tenant_id, store_id, user_id, query,
            embedding=embedding,
            top_k=top_k,
            memory_types=memory_types,
            categories=categories,
        )

        # 批量递增 access_count
        if results:
            memory_ids = [UUID(r["id"]) for r in results]
            now = datetime.now(timezone.utc)
            await self.db.execute(
                update(AgentMemory)
                .where(AgentMemory.id.in_(memory_ids))
                .values(
                    access_count=AgentMemory.access_count + 1,
                    last_accessed_at=now,
                )
            )

        logger.info(
            "memory_recalled",
            tenant_id=tenant_id,
            query_len=len(query),
            results_count=len(results),
        )
        return results

    async def get_store_profile(self, tenant_id: str, store_id: str) -> dict:
        """聚合门店画像：该门店所有有效长期记忆，按 category 分组"""
        now = datetime.now(timezone.utc)

        stmt = (
            select(AgentMemory)
            .where(
                AgentMemory.tenant_id == UUID(tenant_id),
                AgentMemory.store_id == UUID(store_id),
                AgentMemory.is_deleted == False,  # noqa: E712
                (AgentMemory.valid_until.is_(None)) | (AgentMemory.valid_until > now),
            )
            .order_by(AgentMemory.importance.desc())
        )
        result = await self.db.execute(stmt)
        memories = result.scalars().all()

        profile: dict[str, list[dict]] = {}
        for m in memories:
            cat = m.category or "uncategorized"
            if cat not in profile:
                profile[cat] = []
            profile[cat].append({
                "id": str(m.id),
                "memory_key": m.memory_key,
                "content": m.content,
                "confidence": m.confidence,
                "importance": m.importance,
                "memory_type": m.memory_type,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            })

        logger.info(
            "store_profile_aggregated",
            tenant_id=tenant_id,
            store_id=store_id,
            categories=len(profile),
            total_memories=len(memories),
        )
        return {
            "store_id": store_id,
            "categories": profile,
            "total_memories": len(memories),
        }

    async def get_user_profile(self, tenant_id: str, user_id: str) -> dict:
        """聚合用户画像：该用户的偏好、习惯、关注点"""
        now = datetime.now(timezone.utc)

        stmt = (
            select(AgentMemory)
            .where(
                AgentMemory.tenant_id == UUID(tenant_id),
                AgentMemory.user_id == UUID(user_id),
                AgentMemory.is_deleted == False,  # noqa: E712
                (AgentMemory.valid_until.is_(None)) | (AgentMemory.valid_until > now),
            )
            .order_by(AgentMemory.importance.desc())
        )
        result = await self.db.execute(stmt)
        memories = result.scalars().all()

        profile: dict[str, list[dict]] = {}
        for m in memories:
            cat = m.category or "uncategorized"
            if cat not in profile:
                profile[cat] = []
            profile[cat].append({
                "id": str(m.id),
                "memory_key": m.memory_key,
                "content": m.content,
                "confidence": m.confidence,
                "importance": m.importance,
                "memory_type": m.memory_type,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            })

        logger.info(
            "user_profile_aggregated",
            tenant_id=tenant_id,
            user_id=user_id,
            categories=len(profile),
            total_memories=len(memories),
        )
        return {
            "user_id": user_id,
            "categories": profile,
            "total_memories": len(memories),
        }

    # ══════════════════════════════════════════════════════════════
    # 情景记忆
    # ══════════════════════════════════════════════════════════════

    async def record_episode(
        self,
        tenant_id: str,
        store_id: str,
        episode_type: str,
        episode_date: str,
        time_slot: str | None,
        context: dict,
        action_taken: dict | None,
        outcome: dict | None,
        lesson: str | None = None,
    ) -> AgentEpisode:
        """记录一个情景（事件/决策/异常/成功）"""
        episode = AgentEpisode(
            tenant_id=UUID(tenant_id),
            store_id=UUID(store_id),
            episode_type=episode_type,
            episode_date=date.fromisoformat(episode_date),
            time_slot=time_slot,
            context=context,
            action_taken=action_taken,
            outcome=outcome,
            lesson=lesson,
        )
        self.db.add(episode)
        await self.db.flush()

        await self._log_history(
            tenant_id, str(episode.id), "agent_episodes",
            "ADD", None,
            {"episode_type": episode_type, "lesson": lesson},
            reason="episode recorded",
        )

        logger.info(
            "episode_recorded",
            episode_id=str(episode.id),
            episode_type=episode_type,
            store_id=store_id,
            episode_date=episode_date,
        )
        return episode

    async def find_similar_episodes(
        self,
        tenant_id: str,
        store_id: str,
        query: str,
        *,
        limit: int = 5,
    ) -> list[AgentEpisode]:
        """搜索过去相似的情景（基于 lesson 和 context 文本匹配）

        TODO: 后续接入向量搜索提升精度
        """
        safe_query = query.replace("%", r"\%").replace("_", r"\_")

        stmt = (
            select(AgentEpisode)
            .where(
                AgentEpisode.tenant_id == UUID(tenant_id),
                AgentEpisode.store_id == UUID(store_id),
                AgentEpisode.is_deleted == False,  # noqa: E712
            )
            .where(
                AgentEpisode.lesson.ilike(f"%{safe_query}%")
            )
            .order_by(AgentEpisode.episode_date.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ══════════════════════════════════════════════════════════════
    # 过程性记忆
    # ══════════════════════════════════════════════════════════════

    async def learn_procedure(
        self,
        tenant_id: str,
        store_id: str | None,
        procedure_name: str,
        trigger_pattern: str,
        trigger_config: dict,
        action_template: dict,
    ) -> AgentProcedure:
        """学习一条新规则/策略"""
        procedure = AgentProcedure(
            tenant_id=UUID(tenant_id),
            store_id=UUID(store_id) if store_id else None,
            procedure_name=procedure_name,
            trigger_pattern=trigger_pattern,
            trigger_config=trigger_config,
            action_template=action_template,
        )
        self.db.add(procedure)
        await self.db.flush()

        await self._log_history(
            tenant_id, str(procedure.id), "agent_procedures",
            "ADD", None,
            {"procedure_name": procedure_name, "trigger_pattern": trigger_pattern},
            reason="procedure learned",
        )

        logger.info(
            "procedure_learned",
            procedure_id=str(procedure.id),
            procedure_name=procedure_name,
            trigger_pattern=trigger_pattern,
        )
        return procedure

    async def update_procedure_outcome(
        self,
        tenant_id: str,
        procedure_id: str,
        success: bool,
    ) -> None:
        """更新过程性记忆的成功率

        success_rate = (old_rate * old_count + (1 if success else 0)) / (old_count + 1)
        """
        now = datetime.now(timezone.utc)
        pid = UUID(procedure_id)

        stmt = (
            select(AgentProcedure)
            .where(
                AgentProcedure.id == pid,
                AgentProcedure.tenant_id == UUID(tenant_id),
                AgentProcedure.is_deleted == False,  # noqa: E712
            )
        )
        result = await self.db.execute(stmt)
        procedure = result.scalars().first()

        if not procedure:
            logger.warning("procedure_not_found", procedure_id=procedure_id)
            return

        old_count = procedure.execution_count
        old_rate = procedure.success_rate
        new_count = old_count + 1
        new_rate = (old_rate * old_count + (1.0 if success else 0.0)) / new_count

        old_snapshot = {
            "success_rate": old_rate,
            "execution_count": old_count,
        }

        procedure.success_rate = new_rate
        procedure.execution_count = new_count
        procedure.last_executed = now
        await self.db.flush()

        await self._log_history(
            tenant_id, procedure_id, "agent_procedures",
            "UPDATE",
            old_snapshot,
            {"success_rate": new_rate, "execution_count": new_count},
            reason=f"outcome={'success' if success else 'failure'}",
        )

        logger.info(
            "procedure_outcome_updated",
            procedure_id=procedure_id,
            success=success,
            new_rate=round(new_rate, 4),
            execution_count=new_count,
        )

    async def get_matching_procedures(
        self,
        tenant_id: str,
        store_id: str | None,
        trigger_pattern: str,
    ) -> list[AgentProcedure]:
        """查找匹配的过程性记忆"""
        stmt = (
            select(AgentProcedure)
            .where(
                AgentProcedure.tenant_id == UUID(tenant_id),
                AgentProcedure.is_deleted == False,  # noqa: E712
                AgentProcedure.is_active == True,  # noqa: E712
                AgentProcedure.trigger_pattern == trigger_pattern,
            )
        )

        if store_id:
            stmt = stmt.where(
                (AgentProcedure.store_id == UUID(store_id))
                | (AgentProcedure.store_id.is_(None))
            )
        else:
            stmt = stmt.where(AgentProcedure.store_id.is_(None))

        stmt = stmt.order_by(AgentProcedure.success_rate.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ══════════════════════════════════════════════════════════════
    # 记忆维护
    # ══════════════════════════════════════════════════════════════

    async def decay_memories(self, tenant_id: str) -> int:
        """时间衰减：confidence *= e^(-0.01 * days_since_last_access)

        低于 0.1 的记忆标记 valid_until = now（软过期）。
        Returns: 衰减处理的记忆条数
        """
        now = datetime.now(timezone.utc)
        tid = UUID(tenant_id)

        stmt = (
            select(AgentMemory)
            .where(
                AgentMemory.tenant_id == tid,
                AgentMemory.is_deleted == False,  # noqa: E712
                (AgentMemory.valid_until.is_(None)) | (AgentMemory.valid_until > now),
            )
        )
        result = await self.db.execute(stmt)
        memories = result.scalars().all()

        decayed_count = 0
        for m in memories:
            last_access = m.last_accessed_at or m.updated_at or m.created_at
            if not last_access:
                continue

            days = (now - last_access).total_seconds() / 86400.0
            decay_factor = math.exp(-_DECAY_LAMBDA * days)
            new_confidence = m.confidence * decay_factor

            if abs(new_confidence - m.confidence) < 0.001:
                continue  # 变化太小，跳过

            old_confidence = m.confidence
            m.confidence = max(new_confidence, 0.0)

            # 低于阈值则软过期
            if m.confidence < _DECAY_FLOOR:
                m.valid_until = now
                await self._log_history(
                    tenant_id, str(m.id), "agent_memories",
                    "DECAY",
                    {"confidence": old_confidence},
                    {"confidence": m.confidence, "valid_until": now.isoformat()},
                    reason="confidence below threshold",
                    actor="system",
                )

            decayed_count += 1

        if decayed_count > 0:
            await self.db.flush()

        logger.info(
            "memories_decayed",
            tenant_id=tenant_id,
            total_checked=len(memories),
            decayed_count=decayed_count,
        )
        return decayed_count

    async def consolidate_memories(self, tenant_id: str) -> dict:
        """记忆整合：清理过期记忆 + 统计

        Returns: {"expired_cleaned": int, "total_active": int}
        """
        now = datetime.now(timezone.utc)
        tid = UUID(tenant_id)

        # 1. 清理已过期记忆（valid_until < now 且未标记删除的）
        expire_stmt = (
            update(AgentMemory)
            .where(
                AgentMemory.tenant_id == tid,
                AgentMemory.is_deleted == False,  # noqa: E712
                AgentMemory.valid_until.isnot(None),
                AgentMemory.valid_until < now,
            )
            .values(is_deleted=True)
        )
        expire_result = await self.db.execute(expire_stmt)
        expired_count = expire_result.rowcount

        # 2. 统计剩余活跃记忆
        active_stmt = (
            select(func.count())
            .select_from(AgentMemory)
            .where(
                AgentMemory.tenant_id == tid,
                AgentMemory.is_deleted == False,  # noqa: E712
            )
        )
        active_result = await self.db.execute(active_stmt)
        active_count = active_result.scalar() or 0

        logger.info(
            "memories_consolidated",
            tenant_id=tenant_id,
            expired_cleaned=expired_count,
            total_active=active_count,
        )
        return {
            "expired_cleaned": expired_count,
            "total_active": active_count,
        }

    # ══════════════════════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════════════════════

    async def _generate_embedding(self, text_input: str) -> list[float] | None:
        """生成文本向量 embedding

        尝试调用外部 embedding API，失败则返回 None（降级为纯文本搜索）。
        """
        if not _EMBEDDING_API_URL or not _EMBEDDING_API_KEY:
            logger.debug("embedding_skipped", reason="no API configured")
            return None

        try:
            async with httpx.AsyncClient(timeout=_EMBEDDING_TIMEOUT) as client:
                resp = await client.post(
                    _EMBEDDING_API_URL,
                    headers={
                        "Authorization": f"Bearer {_EMBEDDING_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={"input": text_input, "model": "text-embedding-3-small"},
                )
                resp.raise_for_status()
                data = resp.json()
                # 兼容 OpenAI 格式
                embedding = data.get("data", [{}])[0].get("embedding")
                if embedding and isinstance(embedding, list):
                    return embedding
                logger.warning("embedding_unexpected_format", data_keys=list(data.keys()))
                return None
        except httpx.TimeoutException:
            logger.warning("embedding_timeout", url=_EMBEDDING_API_URL)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "embedding_api_error",
                status=exc.response.status_code,
                url=_EMBEDDING_API_URL,
            )
            return None
        except httpx.RequestError as exc:
            logger.warning("embedding_request_error", error=str(exc))
            return None

    async def _find_similar_memory(
        self,
        tenant_id: str,
        store_id: str | None,
        user_id: str | None,
        embedding: list[float] | None,
        content_text: str,
        *,
        memory_type: str | None = None,
    ) -> AgentMemory | None:
        """查找最相似的现有记忆

        有 embedding 时用向量搜索（阈值 0.85），否则用精确 key 匹配。
        """
        now = datetime.now(timezone.utc)

        if embedding:
            # 向量搜索
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
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
                "threshold": _SIMILARITY_THRESHOLD,
            }

            if store_id:
                conditions.append("(store_id = :store_id OR store_id IS NULL)")
                params["store_id"] = UUID(store_id)
            if user_id:
                conditions.append("(user_id = :user_id OR user_id IS NULL)")
                params["user_id"] = UUID(user_id)
            if memory_type:
                conditions.append("memory_type = :memory_type")
                params["memory_type"] = memory_type

            where_clause = " AND ".join(conditions)
            sql = text(f"""
                SELECT id,
                       1 - (embedding <=> :query_embedding::vector) AS similarity
                FROM agent_memories
                WHERE {where_clause}
                ORDER BY similarity DESC
                LIMIT 1
            """)
            result = await self.db.execute(sql, params)
            row = result.mappings().first()

            if row and float(row["similarity"]) >= _SIMILARITY_THRESHOLD:
                # 用 ORM 加载完整对象
                stmt = select(AgentMemory).where(AgentMemory.id == row["id"])
                orm_result = await self.db.execute(stmt)
                return orm_result.scalars().first()

        else:
            # 降级：精确 key 匹配
            key = content_text[:200]
            stmt = (
                select(AgentMemory)
                .where(
                    AgentMemory.tenant_id == UUID(tenant_id),
                    AgentMemory.is_deleted == False,  # noqa: E712
                    AgentMemory.memory_key == key,
                    (AgentMemory.valid_until.is_(None)) | (AgentMemory.valid_until > now),
                )
            )
            if store_id:
                stmt = stmt.where(AgentMemory.store_id == UUID(store_id))
            if memory_type:
                stmt = stmt.where(AgentMemory.memory_type == memory_type)

            stmt = stmt.order_by(AgentMemory.updated_at.desc()).limit(1)
            result = await self.db.execute(stmt)
            return result.scalars().first()

        return None

    async def _create_memory(
        self,
        *,
        tenant_id: str,
        store_id: str | None,
        user_id: str | None,
        agent_id: str,
        memory_type: str,
        memory_key: str,
        content: dict,
        category: str,
        embedding: list[float] | None,
        importance: float,
        source_event: str | None = None,
        access_count: int = 0,
    ) -> AgentMemory:
        """创建一条记忆记录（内部统一入口）"""
        now = datetime.now(timezone.utc)

        # 确定 scope
        if user_id:
            scope = "user"
        elif store_id:
            scope = "store"
        else:
            scope = "tenant"

        memory = AgentMemory(
            tenant_id=UUID(tenant_id),
            agent_id=agent_id,
            memory_type=memory_type,
            memory_key=memory_key,
            content=content,
            confidence=1.0,
            store_id=UUID(store_id) if store_id else None,
            user_id=UUID(user_id) if user_id else None,
            scope=scope,
            category=category,
            importance=importance,
            valid_from=now,
            source_event=source_event,
            access_count=access_count,
            last_accessed_at=now,
        )
        self.db.add(memory)
        await self.db.flush()

        # 写入 embedding（通过 raw SQL，因 ORM 不直接映射 vector 类型）
        if embedding:
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
            await self.db.execute(
                text(
                    "UPDATE agent_memories SET embedding = :emb::vector "
                    "WHERE id = :mid"
                ),
                {"emb": embedding_str, "mid": memory.id},
            )

        return memory

    async def _log_history(
        self,
        tenant_id: str,
        memory_id: str,
        memory_table: str,
        event_type: str,
        old_value: dict | None,
        new_value: dict | None,
        reason: str | None,
        actor: str = "agent",
    ) -> None:
        """写入记忆变更审计日志"""
        history = AgentMemoryHistory(
            tenant_id=UUID(tenant_id),
            memory_id=UUID(memory_id),
            memory_table=memory_table,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            actor=actor,
        )
        self.db.add(history)
        await self.db.flush()

    def _calculate_scope_priority(
        self,
        memory: AgentMemory,
        user_id: str | None,
        store_id: str | None,
    ) -> int:
        """三级作用域优先级：user(3) > store(2) > tenant(1)"""
        if user_id and memory.user_id and str(memory.user_id) == user_id:
            return 3
        if store_id and memory.store_id and str(memory.store_id) == store_id:
            return 2
        return 1
