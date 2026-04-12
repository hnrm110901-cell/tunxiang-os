"""社区发现 -- 对知识图谱节点聚类 + LLM 生成摘要

使用 BFS 连通分量算法对图谱节点进行社区划分，
然后为每个社区生成 LLM 摘要用于高层检索。
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-haiku-4-5-20251001"


class CommunityDetector:
    """知识图谱社区发现"""

    @staticmethod
    async def detect_communities(tenant_id: str, db: Any) -> int:
        """检测社区（连通分量）并更新 kg_communities 表。

        Returns: 社区数量
        """
        try:
            from sqlalchemy import text as sql_text

            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            # 1. 获取所有节点和边
            nodes_result = await db.execute(sql_text("""
                SELECT id::text FROM kg_nodes WHERE tenant_id = :tid::uuid AND is_deleted = false
            """), {"tid": tenant_id})
            all_nodes = [r[0] for r in nodes_result.fetchall()]

            edges_result = await db.execute(sql_text("""
                SELECT from_node_id::text, to_node_id::text FROM kg_edges
                WHERE tenant_id = :tid::uuid AND is_deleted = false
            """), {"tid": tenant_id})
            edges = [(r[0], r[1]) for r in edges_result.fetchall()]

            if not all_nodes:
                return 0

            # 2. BFS 连通分量
            adj: dict[str, set[str]] = defaultdict(set)
            for a, b in edges:
                adj[a].add(b)
                adj[b].add(a)

            visited: set[str] = set()
            communities: list[list[str]] = []

            for node in all_nodes:
                if node in visited:
                    continue
                # BFS
                component: list[str] = []
                queue = [node]
                while queue:
                    current = queue.pop(0)
                    if current in visited:
                        continue
                    visited.add(current)
                    component.append(current)
                    for neighbor in adj.get(current, set()):
                        if neighbor not in visited:
                            queue.append(neighbor)
                if component:
                    communities.append(component)

            # 3. 写入 kg_communities + 更新节点的 community_id
            # 先清理旧社区
            await db.execute(sql_text("""
                DELETE FROM kg_communities WHERE tenant_id = :tid::uuid
            """), {"tid": tenant_id})

            for i, component in enumerate(communities):
                # 创建社区记录
                await db.execute(sql_text("""
                    INSERT INTO kg_communities (tenant_id, label, node_count)
                    VALUES (:tid::uuid, :label, :count)
                """), {"tid": tenant_id, "label": f"社区-{i + 1}", "count": len(component)})

                # 获取刚插入的 community_id
                cid_result = await db.execute(sql_text("""
                    SELECT id FROM kg_communities
                    WHERE tenant_id = :tid::uuid AND label = :label
                    ORDER BY id DESC LIMIT 1
                """), {"tid": tenant_id, "label": f"社区-{i + 1}"})
                cid_row = cid_result.fetchone()
                community_id = cid_row[0] if cid_row else i + 1

                # 更新节点的 community_id
                for node_id in component:
                    await db.execute(sql_text("""
                        UPDATE kg_nodes SET community_id = :cid
                        WHERE id = :nid::uuid AND tenant_id = :tid::uuid
                    """), {"cid": community_id, "nid": node_id, "tid": tenant_id})

            await db.commit()

            logger.info(
                "community_detection_done",
                tenant_id=tenant_id,
                community_count=len(communities),
                total_nodes=len(all_nodes),
            )
            return len(communities)

        except Exception as exc:
            logger.warning("community_detection_failed", error=str(exc), exc_info=True)
            return 0

    @staticmethod
    async def refresh_community_summaries(tenant_id: str, db: Any) -> int:
        """为每个社区生成 LLM 摘要。

        Returns: 已更新的社区数量
        """
        try:
            from sqlalchemy import text as sql_text

            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            # 获取所有社区
            result = await db.execute(sql_text("""
                SELECT id, label, node_count FROM kg_communities
                WHERE tenant_id = :tid::uuid AND is_deleted = false
            """), {"tid": tenant_id})
            communities = result.fetchall()

            updated = 0
            for comm_id, comm_label, node_count in communities:
                # 获取社区中的节点
                nodes_result = await db.execute(sql_text("""
                    SELECT label, name FROM kg_nodes
                    WHERE community_id = :cid AND tenant_id = :tid::uuid AND is_deleted = false
                    LIMIT 20
                """), {"cid": comm_id, "tid": tenant_id})
                nodes = nodes_result.fetchall()

                if not nodes:
                    continue

                # 生成摘要
                node_descriptions = [f"{n[0]}:{n[1]}" for n in nodes]
                summary = await _generate_summary(node_descriptions, comm_label)

                if summary:
                    await db.execute(sql_text("""
                        UPDATE kg_communities SET summary = :summary, updated_at = NOW()
                        WHERE id = :cid AND tenant_id = :tid::uuid
                    """), {"summary": summary, "cid": comm_id, "tid": tenant_id})
                    updated += 1

            await db.commit()
            return updated

        except Exception as exc:
            logger.warning("refresh_summaries_failed", error=str(exc), exc_info=True)
            return 0


async def _generate_summary(node_descriptions: list[str], community_label: str) -> str:
    """使用 Claude 生成社区摘要"""
    if not _ANTHROPIC_API_KEY:
        # 降级：简单拼接
        return f"{community_label}包含：" + "、".join(node_descriptions[:10])

    try:
        nodes_text = "\n".join(f"- {d}" for d in node_descriptions)
        prompt = f"""请为以下餐饮知识图谱节点群组生成一段简洁摘要（50-100字）：

{nodes_text}

摘要应说明这组节点的共同主题和关键内容。只返回摘要文字。"""

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _API_URL,
                json={"model": _MODEL, "max_tokens": 200, "messages": [{"role": "user", "content": prompt}]},
                headers={
                    "x-api-key": _ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("content", [{}])[0].get("text", "")
    except Exception as exc:
        logger.warning("generate_summary_failed", error=str(exc), exc_info=True)

    return f"{community_label}包含：" + "、".join(node_descriptions[:10])
