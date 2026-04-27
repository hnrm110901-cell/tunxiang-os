"""检索质量日志 — 记录每次查询的完整链路

用于监控和持续优化检索质量：
- 查询复杂度分布
- 检索延迟 P50/P99
- Corrective RAG 触发率
- 平均相关度分数
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


class KnowledgeQueryLogger:
    """检索质量日志写入器"""

    @staticmethod
    async def log_query(
        tenant_id: str,
        query: str,
        collection: str | None,
        complexity: str,
        retrieved_count: int,
        reranked_count: int,
        relevance_max: float | None,
        latency_ms: int,
        rewrite_count: int,
        answer_source: str,
        db: Any,
    ) -> None:
        """记录一次检索日志到 knowledge_query_logs 表。

        即使写入失败也不影响主流程（fire and forget）。
        """
        try:
            from sqlalchemy import text as sql_text

            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            await db.execute(
                sql_text("""
                INSERT INTO knowledge_query_logs (
                    tenant_id, query, collection, query_complexity,
                    retrieved_count, reranked_count, relevance_max,
                    latency_ms, rewrite_count, answer_source
                ) VALUES (
                    :tenant_id::uuid, :query, :collection, :complexity,
                    :retrieved_count, :reranked_count, :relevance_max,
                    :latency_ms, :rewrite_count, :answer_source
                )
            """),
                {
                    "tenant_id": tenant_id,
                    "query": query[:2000],  # 截断过长查询
                    "collection": collection,
                    "complexity": complexity,
                    "retrieved_count": retrieved_count,
                    "reranked_count": reranked_count,
                    "relevance_max": relevance_max,
                    "latency_ms": latency_ms,
                    "rewrite_count": rewrite_count,
                    "answer_source": answer_source,
                },
            )

            await db.commit()

        except Exception as exc:
            # 日志写入失败不影响主流程
            logger.warning("query_log_write_failed", error=str(exc), exc_info=True)

    @staticmethod
    async def get_query_stats(
        tenant_id: str,
        db: Any,
        days: int = 7,
    ) -> dict[str, Any]:
        """获取检索质量统计（最近 N 天）"""
        try:
            from sqlalchemy import text as sql_text

            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            result = await db.execute(
                sql_text("""
                SELECT
                    COUNT(*) AS total_queries,
                    AVG(latency_ms) AS avg_latency_ms,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_latency_ms,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99_latency_ms,
                    AVG(relevance_max) AS avg_relevance,
                    SUM(CASE WHEN rewrite_count > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS corrective_rate,
                    COUNT(DISTINCT collection) AS collection_count
                FROM knowledge_query_logs
                WHERE tenant_id = :tenant_id::uuid
                AND created_at >= NOW() - MAKE_INTERVAL(days => :days)
            """),
                {"tenant_id": tenant_id, "days": days},
            )

            row = result.fetchone()
            if not row:
                return {}

            return {
                "total_queries": row[0] or 0,
                "avg_latency_ms": round(float(row[1] or 0), 1),
                "p50_latency_ms": round(float(row[2] or 0), 1),
                "p99_latency_ms": round(float(row[3] or 0), 1),
                "avg_relevance": round(float(row[4] or 0), 3),
                "corrective_rate": round(float(row[5] or 0), 3),
                "collection_count": row[6] or 0,
            }

        except Exception as exc:
            logger.warning("query_stats_failed", error=str(exc), exc_info=True)
            return {}
