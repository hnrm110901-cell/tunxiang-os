"""内容发布工作器 — 定时检查到期内容并发布到渠道

运行方式：
    APScheduler 每5分钟调用 ContentPublisher().tick(db)

流程：
    1. 查找 status='scheduled' 且 scheduled_at <= NOW() 的内容
    2. 逐条调用 ChannelEngine 发布到目标渠道
    3. 更新状态为 'published' 或 'failed'

S3W11-12 Smart Content Factory
"""

import json

import structlog
from services.channel_engine import ChannelEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_channel_engine = ChannelEngine()

# ---------------------------------------------------------------------------
# ContentPublisher
# ---------------------------------------------------------------------------


class ContentPublisher:
    """内容发布工作器 — 定时扫描并发布到期内容"""

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ------------------------------------------------------------------
    # tick — APScheduler 入口（每5分钟）
    # ------------------------------------------------------------------

    async def tick(self, db: AsyncSession) -> dict:
        """扫描所有到期内容并发布

        注意：tick 不设租户上下文，使用超级用户权限扫描全表。
        每条内容发布时单独设置租户上下文。
        """
        # 使用无 RLS 的查询获取到期内容（需要超级用户/bypass RLS角色）
        result = await db.execute(
            text("""
                SELECT id, tenant_id
                FROM content_calendar
                WHERE status = 'scheduled'
                  AND scheduled_at <= NOW()
                  AND is_deleted = false
                ORDER BY scheduled_at ASC
                LIMIT 50
            """)
        )
        due_items = result.mappings().all()

        published = 0
        failed = 0

        for item in due_items:
            tid = str(item["tenant_id"])
            cid = str(item["id"])
            try:
                res = await self.publish_single(tid, cid, db)
                if res.get("status") == "published":
                    published += 1
                else:
                    failed += 1
            except Exception:
                logger.exception("content_publish_error", content_id=cid, tenant_id=tid)
                failed += 1

        logger.info(
            "content_publisher_tick_done",
            due=len(due_items),
            published=published,
            failed=failed,
        )
        return {"due": len(due_items), "published": published, "failed": failed}

    # ------------------------------------------------------------------
    # 发布单条内容
    # ------------------------------------------------------------------

    async def publish_single(
        self,
        tenant_id: str,
        content_id: str,
        db: AsyncSession,
    ) -> dict:
        """发布单条内容到目标渠道"""
        await self._set_tenant(db, tenant_id)

        # 标记为 publishing
        await db.execute(
            text("""
                UPDATE content_calendar
                SET status = 'publishing', updated_at = NOW()
                WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
            """),
            {"cid": content_id, "tid": tenant_id},
        )

        # 读取内容详情
        row = await db.execute(
            text("""
                SELECT id, content_body, content_type, target_channels, media_urls
                FROM content_calendar
                WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
            """),
            {"cid": content_id, "tid": tenant_id},
        )
        content = row.mappings().first()
        if not content:
            return {"error": "content_not_found", "status": "failed"}

        target_channels = content["target_channels"] or []
        if isinstance(target_channels, str):
            target_channels = json.loads(target_channels)

        channel_results: list[dict] = []
        all_success = True

        for ch_config in target_channels:
            channel = ch_config.get("channel", "wecom_chat") if isinstance(ch_config, dict) else str(ch_config)
            try:
                # 调用 ChannelEngine 发送
                send_result = await _channel_engine.send_message(
                    tenant_id=tenant_id,
                    channel=channel,
                    content=content["content_body"],
                    db=db,
                )
                channel_results.append(
                    {
                        "channel": channel,
                        "success": True,
                        "message_id": send_result.get("message_id"),
                    }
                )
            except Exception:
                logger.exception(
                    "channel_send_error",
                    channel=channel,
                    content_id=content_id,
                )
                channel_results.append(
                    {
                        "channel": channel,
                        "success": False,
                        "error": "send_failed",
                    }
                )
                all_success = False

        # 更新发布结果
        final_status = "published" if all_success else "failed"
        publish_result_json = json.dumps({"channel_results": channel_results}, ensure_ascii=False)

        await db.execute(
            text("""
                UPDATE content_calendar
                SET status = :status,
                    published_at = CASE WHEN :status = 'published' THEN NOW() ELSE published_at END,
                    publish_result = :result::jsonb,
                    updated_at = NOW()
                WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
            """),
            {
                "status": final_status,
                "result": publish_result_json,
                "cid": content_id,
                "tid": tenant_id,
            },
        )
        await db.commit()

        logger.info(
            "content_published",
            content_id=content_id,
            status=final_status,
            channels=len(channel_results),
        )

        return {
            "id": content_id,
            "status": final_status,
            "publish_result": {"channel_results": channel_results},
        }
