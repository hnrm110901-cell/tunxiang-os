"""知识新鲜度监控 — 标记过期内容，通知管理员

检测 > 90 天未审核的 published 文档：
- 定期扫描过期文档
- 触发 agent.knowledge.stale_alert 事件
- 通知管理员审核更新
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

_STALE_THRESHOLD_DAYS = 90


class FreshnessMonitor:
    """知识新鲜度监控"""

    @staticmethod
    async def check_staleness(
        tenant_id: str,
        db: Any,
        threshold_days: int = _STALE_THRESHOLD_DAYS,
    ) -> list[dict[str, Any]]:
        """检测过期的 published 文档。

        Returns: [{id, title, collection, published_at, stale_days}]
        """
        try:
            from sqlalchemy import text as sql_text

            await db.execute(sql_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            result = await db.execute(
                sql_text("""
                SELECT
                    id::text,
                    title,
                    collection,
                    published_at,
                    EXTRACT(DAY FROM NOW() - COALESCE(published_at, created_at))::int AS stale_days
                FROM knowledge_documents
                WHERE tenant_id = :tid::uuid
                AND status = 'published'
                AND is_deleted = false
                AND COALESCE(published_at, created_at) < NOW() - MAKE_INTERVAL(days => :days)
                ORDER BY stale_days DESC
            """),
                {"tid": tenant_id, "days": threshold_days},
            )

            rows = result.fetchall()
            stale_docs = [
                {
                    "id": r[0],
                    "title": r[1],
                    "collection": r[2],
                    "published_at": str(r[3]) if r[3] else None,
                    "stale_days": r[4],
                }
                for r in rows
            ]

            if stale_docs:
                logger.info(
                    "knowledge_stale_docs_found",
                    tenant_id=tenant_id,
                    count=len(stale_docs),
                )

            return stale_docs

        except ImportError as exc:
            logger.warning("check_staleness_import_error", error=str(exc), exc_info=True)
            return []
        except ValueError as exc:
            logger.warning("check_staleness_value_error", error=str(exc), exc_info=True)
            return []

    @staticmethod
    async def notify_stale_documents(
        tenant_id: str,
        stale_docs: list[dict[str, Any]],
    ) -> None:
        """触发过期知识预警事件"""
        if not stale_docs:
            return

        try:
            import asyncio

            from shared.events.src.emitter import emit_event
            from shared.events.src.event_types import KnowledgeEventType

            asyncio.create_task(
                emit_event(
                    event_type=KnowledgeEventType.STALE_ALERT,
                    tenant_id=tenant_id,
                    stream_id=f"knowledge:stale:{tenant_id}",
                    payload={
                        "stale_count": len(stale_docs),
                        "documents": stale_docs[:10],  # 最多包含10条
                        "threshold_days": _STALE_THRESHOLD_DAYS,
                    },
                    source_service="knowledge-monitor",
                )
            )

            logger.info(
                "knowledge_stale_alert_sent",
                tenant_id=tenant_id,
                count=len(stale_docs),
            )

        except ImportError as exc:
            logger.warning("notify_stale_import_error", error=str(exc), exc_info=True)
        except AttributeError as exc:
            logger.warning("notify_stale_attribute_error", error=str(exc), exc_info=True)
