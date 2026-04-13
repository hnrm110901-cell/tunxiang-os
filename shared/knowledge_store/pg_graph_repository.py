"""PostgreSQL-backed 知识图谱存储

替代 OntologyRepository 的内存模式，提供持久化的图谱 CRUD：
- 节点：kg_nodes 表（含向量嵌入用于语义搜索）
- 边：kg_edges 表（支持权重和来源追踪）
- 社区：kg_communities 表（LightRAG 风格社区摘要）
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog

logger = structlog.get_logger()


class PgGraphRepository:
    """PG-backed 知识图谱 CRUD"""

    @staticmethod
    async def upsert_node(
        tenant_id: str,
        label: str,
        name: str,
        properties: dict[str, Any],
        db: Any,
        embedding: list[float] | None = None,
    ) -> str:
        """创建或更新节点（按 tenant_id + label + name 去重）。

        Returns: node_id
        """
        try:
            from sqlalchemy import text as sql_text

            await db.execute(sql_text(
                "SELECT set_config('app.tenant_id', :tid, true)"
            ), {"tid": tenant_id})

            node_id = str(uuid4())
            embedding_str = f"[{','.join(str(x) for x in embedding)}]" if embedding else None

            import json
            props_json = json.dumps(properties, ensure_ascii=False, default=str)

            # Upsert: 按 name + label + tenant_id 去重
            result = await db.execute(sql_text("""
                INSERT INTO kg_nodes (id, tenant_id, label, name, properties, embedding)
                VALUES (:id, :tenant_id::uuid, :label, :name, :properties::jsonb, :embedding::vector)
                ON CONFLICT ON CONSTRAINT uq_kg_nodes_tenant_label_name
                DO UPDATE SET
                    properties = kg_nodes.properties || EXCLUDED.properties,
                    embedding = COALESCE(EXCLUDED.embedding, kg_nodes.embedding),
                    updated_at = NOW()
                RETURNING id::text
            """), {
                "id": node_id,
                "tenant_id": tenant_id,
                "label": label,
                "name": name,
                "properties": props_json,
                "embedding": embedding_str,
            })

            row = result.fetchone()
            await db.commit()
            return row[0] if row else node_id

        except Exception as exc:
            logger.warning("upsert_node_failed", error=str(exc), label=label, name=name, exc_info=True)
            # If unique constraint doesn't exist yet, try plain insert
            try:
                from sqlalchemy import text as sql_text
                import json
                props_json = json.dumps(properties, ensure_ascii=False, default=str)
                embedding_str2 = f"[{','.join(str(x) for x in embedding)}]" if embedding else None
                nid = str(uuid4())
                await db.execute(sql_text("""
                    INSERT INTO kg_nodes (id, tenant_id, label, name, properties, embedding)
                    VALUES (:id, :tenant_id::uuid, :label, :name, :properties::jsonb, :embedding::vector)
                """), {
                    "id": nid, "tenant_id": tenant_id, "label": label,
                    "name": name, "properties": props_json, "embedding": embedding_str2,
                })
                await db.commit()
                return nid
            except Exception as exc2:
                logger.warning("upsert_node_fallback_failed", error=str(exc2), exc_info=True)
                return ""

    @staticmethod
    async def upsert_edge(
        tenant_id: str,
        from_node_id: str,
        to_node_id: str,
        rel_type: str,
        properties: dict[str, Any],
        db: Any,
        weight: float = 1.0,
        source_chunk_id: str | None = None,
    ) -> str:
        """创建边"""
        try:
            from sqlalchemy import text as sql_text
            import json

            await db.execute(sql_text(
                "SELECT set_config('app.tenant_id', :tid, true)"
            ), {"tid": tenant_id})

            edge_id = str(uuid4())
            props_json = json.dumps(properties, ensure_ascii=False, default=str)

            await db.execute(sql_text("""
                INSERT INTO kg_edges (id, tenant_id, from_node_id, to_node_id, rel_type, properties, weight, source_chunk_id)
                VALUES (:id, :tenant_id::uuid, :from_id::uuid, :to_id::uuid, :rel_type, :props::jsonb, :weight, :chunk_id::uuid)
            """), {
                "id": edge_id,
                "tenant_id": tenant_id,
                "from_id": from_node_id,
                "to_id": to_node_id,
                "rel_type": rel_type,
                "props": props_json,
                "weight": weight,
                "chunk_id": source_chunk_id,
            })
            await db.commit()
            return edge_id
        except Exception as exc:
            logger.warning("upsert_edge_failed", error=str(exc), exc_info=True)
            return ""

    @staticmethod
    async def get_node(node_id: str, tenant_id: str, db: Any) -> dict[str, Any] | None:
        """获取节点"""
        try:
            from sqlalchemy import text as sql_text
            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})
            result = await db.execute(sql_text("""
                SELECT id::text, label, name, properties, community_id, created_at, updated_at
                FROM kg_nodes WHERE id = :nid::uuid AND tenant_id = :tid::uuid AND is_deleted = false
            """), {"nid": node_id, "tid": tenant_id})
            row = result.fetchone()
            if not row:
                return None
            return {"id": row[0], "label": row[1], "name": row[2], "properties": row[3] or {},
                    "community_id": row[4], "created_at": str(row[5]), "updated_at": str(row[6])}
        except Exception as exc:
            logger.warning("get_node_failed", error=str(exc), exc_info=True)
            return None

    @staticmethod
    async def get_neighbors(
        node_id: str,
        tenant_id: str,
        db: Any,
        rel_types: list[str] | None = None,
        depth: int = 1,
    ) -> list[dict[str, Any]]:
        """获取邻居节点（1-hop）"""
        try:
            from sqlalchemy import text as sql_text
            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            where_extra = ""
            params: dict[str, Any] = {"nid": node_id, "tid": tenant_id}
            if rel_types:
                placeholders = ", ".join(f":rt{i}" for i in range(len(rel_types)))
                where_extra = f"AND e.rel_type IN ({placeholders})"
                for i, rt in enumerate(rel_types):
                    params[f"rt{i}"] = rt

            result = await db.execute(sql_text(f"""
                SELECT n.id::text, n.label, n.name, n.properties, e.rel_type, e.weight
                FROM kg_edges e
                JOIN kg_nodes n ON (
                    (e.to_node_id = n.id AND e.from_node_id = :nid::uuid)
                    OR (e.from_node_id = n.id AND e.to_node_id = :nid::uuid)
                )
                WHERE e.tenant_id = :tid::uuid AND e.is_deleted = false
                AND n.is_deleted = false {where_extra}
                LIMIT 50
            """), params)

            rows = result.fetchall()
            return [
                {"id": r[0], "label": r[1], "name": r[2], "properties": r[3] or {},
                 "rel_type": r[4], "weight": r[5]}
                for r in rows
            ]
        except Exception as exc:
            logger.warning("get_neighbors_failed", error=str(exc), exc_info=True)
            return []

    @staticmethod
    async def search_nodes_by_name(
        query: str,
        tenant_id: str,
        db: Any,
        label: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """按名称模糊搜索节点"""
        try:
            from sqlalchemy import text as sql_text
            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            where = "tenant_id = :tid::uuid AND is_deleted = false AND name ILIKE :q"
            params: dict[str, Any] = {"tid": tenant_id, "q": f"%{query}%", "top_k": top_k}
            if label:
                where += " AND label = :label"
                params["label"] = label

            result = await db.execute(sql_text(f"""
                SELECT id::text, label, name, properties, community_id
                FROM kg_nodes WHERE {where}
                ORDER BY updated_at DESC LIMIT :top_k
            """), params)

            rows = result.fetchall()
            return [{"id": r[0], "label": r[1], "name": r[2], "properties": r[3] or {},
                     "community_id": r[4]} for r in rows]
        except Exception as exc:
            logger.warning("search_nodes_by_name_failed", error=str(exc), exc_info=True)
            return []

    @staticmethod
    async def search_nodes_by_embedding(
        embedding: list[float],
        tenant_id: str,
        db: Any,
        label: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """按向量相似度搜索节点"""
        try:
            from sqlalchemy import text as sql_text
            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            embedding_str = f"[{','.join(str(x) for x in embedding)}]"
            where = "tenant_id = :tid::uuid AND is_deleted = false AND embedding IS NOT NULL"
            params: dict[str, Any] = {"tid": tenant_id, "emb": embedding_str, "top_k": top_k}
            if label:
                where += " AND label = :label"
                params["label"] = label

            result = await db.execute(sql_text(f"""
                SELECT id::text, label, name, properties,
                       1 - (embedding <=> :emb::vector) AS score
                FROM kg_nodes WHERE {where}
                ORDER BY embedding <=> :emb::vector
                LIMIT :top_k
            """), params)

            rows = result.fetchall()
            return [{"id": r[0], "label": r[1], "name": r[2], "properties": r[3] or {},
                     "score": float(r[4]) if r[4] else 0.0} for r in rows]
        except Exception as exc:
            logger.warning("search_nodes_by_embedding_failed", error=str(exc), exc_info=True)
            return []

    @staticmethod
    async def get_community(community_id: int, tenant_id: str, db: Any) -> dict[str, Any] | None:
        """获取社区信息"""
        try:
            from sqlalchemy import text as sql_text
            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})
            result = await db.execute(sql_text("""
                SELECT id, label, summary, node_count, updated_at
                FROM kg_communities WHERE id = :cid AND tenant_id = :tid::uuid AND is_deleted = false
            """), {"cid": community_id, "tid": tenant_id})
            row = result.fetchone()
            if not row:
                return None
            return {"id": row[0], "label": row[1], "summary": row[2],
                    "node_count": row[3], "updated_at": str(row[4])}
        except Exception as exc:
            logger.warning("get_community_failed", error=str(exc), exc_info=True)
            return None

    @staticmethod
    async def list_communities(tenant_id: str, db: Any) -> list[dict[str, Any]]:
        """列出所有社区"""
        try:
            from sqlalchemy import text as sql_text
            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})
            result = await db.execute(sql_text("""
                SELECT id, label, summary, node_count FROM kg_communities
                WHERE tenant_id = :tid::uuid AND is_deleted = false ORDER BY node_count DESC
            """), {"tid": tenant_id})
            return [{"id": r[0], "label": r[1], "summary": r[2], "node_count": r[3]} for r in result.fetchall()]
        except Exception as exc:
            logger.warning("list_communities_failed", error=str(exc), exc_info=True)
            return []

    @staticmethod
    async def delete_node(node_id: str, tenant_id: str, db: Any) -> bool:
        """软删除节点（及关联边）"""
        try:
            from sqlalchemy import text as sql_text
            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})
            await db.execute(sql_text("""
                UPDATE kg_edges SET is_deleted = true
                WHERE (from_node_id = :nid::uuid OR to_node_id = :nid::uuid) AND tenant_id = :tid::uuid
            """), {"nid": node_id, "tid": tenant_id})
            await db.execute(sql_text("""
                UPDATE kg_nodes SET is_deleted = true, updated_at = NOW()
                WHERE id = :nid::uuid AND tenant_id = :tid::uuid
            """), {"nid": node_id, "tid": tenant_id})
            await db.commit()
            return True
        except Exception as exc:
            logger.warning("delete_node_failed", error=str(exc), exc_info=True)
            return False
