"""小红书评论/笔记采集服务

通过小红书开放平台 API 采集门店关联笔记和评论，
输出结构化数据给 tx-intel 消费者洞察引擎做情感分析。

流程：
  1. 遍历所有已绑定 POI
  2. 拉取最新笔记列表
  3. 拉取每篇笔记的评论
  4. 输出标准化格式 → tx-intel consumer_insight 消费
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .xhs_client import XHSClient

logger = structlog.get_logger(__name__)


class XHSReviewCrawler:
    """小红书评论采集器"""

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.client = XHSClient(app_id=app_id, app_secret=app_secret)

    async def crawl_store_reviews(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        max_notes: int = 50,
    ) -> dict[str, Any]:
        """采集单个门店的小红书笔记和评论

        Returns:
            {
                "store_id": str,
                "notes_count": int,
                "comments_count": int,
                "reviews": [
                    {
                        "source": "xiaohongshu",
                        "note_id": str,
                        "title": str,
                        "author": str,
                        "content": str,
                        "likes": int,
                        "comments_count": int,
                        "published_at": str,
                        "comments": [
                            {"author": str, "content": str, "created_at": str}
                        ]
                    }
                ]
            }
        """
        tid = uuid.UUID(tenant_id)
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        poi_row = await db.execute(
            text("""
                SELECT xhs_poi_id FROM xhs_poi_mappings
                WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
            """),
            {"tid": tid, "sid": uuid.UUID(store_id)},
        )
        poi = poi_row.fetchone()
        if not poi or not poi.xhs_poi_id:
            return {"store_id": store_id, "notes_count": 0, "comments_count": 0, "reviews": [], "error": "store_not_bound"}

        notes_resp = await self.client.get_store_notes(poi.xhs_poi_id, page=1, size=max_notes)
        notes_data = notes_resp.get("data", {}).get("notes", [])

        reviews = []
        total_comments = 0

        for note in notes_data:
            note_id = note.get("note_id", "")
            comments_resp = await self.client.get_note_comments(note_id, page=1, size=50)
            comments_data = comments_resp.get("data", {}).get("comments", [])
            total_comments += len(comments_data)

            reviews.append({
                "source": "xiaohongshu",
                "note_id": note_id,
                "title": note.get("title", ""),
                "author": note.get("author", ""),
                "content": note.get("content", ""),
                "likes": note.get("likes", 0),
                "comments_count": len(comments_data),
                "published_at": note.get("published_at", ""),
                "comments": [
                    {
                        "author": c.get("author", ""),
                        "content": c.get("content", ""),
                        "created_at": c.get("created_at", ""),
                    }
                    for c in comments_data
                ],
            })

        logger.info(
            "xhs.reviews_crawled",
            store_id=store_id,
            notes_count=len(reviews),
            comments_count=total_comments,
        )
        return {
            "store_id": store_id,
            "notes_count": len(reviews),
            "comments_count": total_comments,
            "reviews": reviews,
        }

    async def crawl_all_stores(
        self,
        tenant_id: str,
        db: AsyncSession,
        max_notes_per_store: int = 20,
    ) -> dict[str, Any]:
        """批量采集所有已绑定门店的评论"""
        tid = uuid.UUID(tenant_id)
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        rows = await db.execute(
            text("""
                SELECT store_id, xhs_poi_id FROM xhs_poi_mappings
                WHERE tenant_id = :tid AND xhs_poi_id != '' AND is_deleted = false
            """),
            {"tid": tid},
        )
        bindings = rows.fetchall()

        all_reviews = []
        total_notes = 0
        total_comments = 0

        for binding in bindings:
            result = await self.crawl_store_reviews(
                store_id=str(binding.store_id),
                tenant_id=tenant_id,
                db=db,
                max_notes=max_notes_per_store,
            )
            all_reviews.extend(result["reviews"])
            total_notes += result["notes_count"]
            total_comments += result["comments_count"]

        logger.info(
            "xhs.batch_crawl_done",
            stores=len(bindings),
            total_notes=total_notes,
            total_comments=total_comments,
        )
        return {
            "stores_crawled": len(bindings),
            "total_notes": total_notes,
            "total_comments": total_comments,
            "reviews": all_reviews,
        }

    @staticmethod
    def to_intel_format(reviews: list[dict]) -> list[dict]:
        """转换为 tx-intel consumer_insight 标准输入格式

        tx-intel 期望格式:
        [{"platform": str, "text": str, "author": str, "rating": float, "date": str, "store_id": str}]
        """
        intel_records = []
        for review in reviews:
            intel_records.append({
                "platform": "xiaohongshu",
                "text": review.get("title", "") + " " + review.get("content", ""),
                "author": review.get("author", ""),
                "rating": None,
                "date": review.get("published_at", ""),
                "metadata": {
                    "note_id": review.get("note_id"),
                    "likes": review.get("likes", 0),
                },
            })
            for comment in review.get("comments", []):
                intel_records.append({
                    "platform": "xiaohongshu",
                    "text": comment.get("content", ""),
                    "author": comment.get("author", ""),
                    "rating": None,
                    "date": comment.get("created_at", ""),
                    "metadata": {"note_id": review.get("note_id"), "type": "comment"},
                })
        return intel_records
