"""AI评论自动回复服务 — 品牌语调智能回复

负责：
  - 读取order_reviews评论，调用tx-brain Claude API生成品牌语调回复
  - 回复审批流程（draft → approved → posted）
  - 品牌语调配置管理
  - 差评自动批量生成回复
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# 默认品牌语调配置
_DEFAULT_BRAND_VOICE = {
    "tone": "warm",
    "style": "亲切关怀",
    "keywords": ["感谢", "期待再次光临", "持续改进"],
}

# 回复生成提示词模板
_REPLY_PROMPT_TEMPLATE = (
    "你是{brand_name}的客户关系经理。请用{tone}的语气回复以下{rating}星评价。\n"
    "规则：1)先感谢 2)对问题表示歉意 3)给出改进承诺 4)邀请再次光临\n"
    "不超过100字。\n"
    "评价内容：{review_text}"
)


class ReviewReplier:
    """AI评论自动回复服务

    通过 Claude API 生成符合品牌语调的评论回复，
    支持审批流程和批量差评回复。
    """

    async def generate_reply(
        self,
        tenant_id: uuid.UUID,
        review_id: uuid.UUID,
        db: AsyncSession,
        brand_voice_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """读取评论并生成AI回复，存储为draft状态

        参数：
          - tenant_id: 租户ID
          - review_id: order_reviews表中的评论ID
          - db: 数据库会话
          - brand_voice_config: 可选的品牌语调配置覆盖

        返回生成结果摘要。
        """
        log = logger.bind(tenant_id=str(tenant_id), review_id=str(review_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 1. 读取评论
        result = await db.execute(
            text("""
                SELECT id, platform, rating, review_text, store_id
                FROM order_reviews
                WHERE id = :review_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"review_id": str(review_id), "tenant_id": str(tenant_id)},
        )
        review_row = result.fetchone()
        if not review_row:
            log.warning("review_replier.review_not_found")
            raise ValueError(f"评论不存在: {review_id}")

        platform = review_row[1]
        rating = float(review_row[2]) if review_row[2] is not None else None
        review_text = review_row[3] or ""

        # 2. 获取品牌语调配置
        if brand_voice_config is None:
            brand_voice_config = await self.get_brand_voice_config(tenant_id, db)

        tone = brand_voice_config.get("tone", "warm")
        tone_map = {"warm": "温暖亲切", "professional": "专业正式", "casual": "轻松随和"}
        tone_desc = tone_map.get(tone, "温暖亲切")

        # 3. 获取品牌名称
        brand_name = await self._get_brand_name(tenant_id, db)

        # 4. 构建提示词
        prompt = _REPLY_PROMPT_TEMPLATE.format(
            brand_name=brand_name,
            tone=tone_desc,
            rating=rating if rating else "未评分",
            review_text=review_text[:500],
        )

        # 5. 调用tx-brain Claude API生成回复
        generated_reply = await self._call_ai_generate(prompt, log)

        # 6. 写入review_auto_replies
        reply_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO review_auto_replies (
                    id, tenant_id, review_id, platform,
                    original_rating, original_text, generated_reply,
                    brand_voice_config, model_used, status
                ) VALUES (
                    :id, :tenant_id, :review_id, :platform,
                    :original_rating, :original_text, :generated_reply,
                    :brand_voice_config::jsonb, :model_used, 'draft'
                )
            """),
            {
                "id": str(reply_id),
                "tenant_id": str(tenant_id),
                "review_id": str(review_id),
                "platform": platform,
                "original_rating": rating,
                "original_text": review_text,
                "generated_reply": generated_reply,
                "brand_voice_config": json.dumps(brand_voice_config, ensure_ascii=False),
                "model_used": "claude-haiku",
            },
        )
        await db.commit()

        log.info(
            "review_replier.reply_generated",
            reply_id=str(reply_id),
            platform=platform,
            rating=rating,
        )
        return {
            "reply_id": str(reply_id),
            "review_id": str(review_id),
            "generated_reply": generated_reply,
            "status": "draft",
            "platform": platform,
            "original_rating": rating,
        }

    async def approve_reply(
        self,
        tenant_id: uuid.UUID,
        reply_id: uuid.UUID,
        approved_by: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """审批通过一条AI回复

        参数：
          - tenant_id: 租户ID
          - reply_id: review_auto_replies中的回复ID
          - approved_by: 审批人ID
          - db: 数据库会话
        """
        log = logger.bind(tenant_id=str(tenant_id), reply_id=str(reply_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(tz=timezone.utc)
        result = await db.execute(
            text("""
                UPDATE review_auto_replies
                SET status = 'approved',
                    approved_by = :approved_by,
                    approved_at = :approved_at,
                    updated_at = :updated_at
                WHERE id = :reply_id
                  AND tenant_id = :tenant_id
                  AND status = 'draft'
                  AND is_deleted = false
                RETURNING id, generated_reply
            """),
            {
                "reply_id": str(reply_id),
                "tenant_id": str(tenant_id),
                "approved_by": str(approved_by),
                "approved_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        row = result.fetchone()
        if not row:
            log.warning("review_replier.approve_failed", reason="reply_not_found_or_wrong_status")
            raise ValueError(f"回复不存在或状态不正确: {reply_id}")

        await db.commit()
        log.info("review_replier.reply_approved", approved_by=str(approved_by))
        return {"reply_id": str(reply_id), "status": "approved"}

    async def post_reply(
        self,
        tenant_id: uuid.UUID,
        reply_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """发布回复到平台（占位实现，待接入平台API）

        参数：
          - tenant_id: 租户ID
          - reply_id: review_auto_replies中的回复ID
          - db: 数据库会话
        """
        log = logger.bind(tenant_id=str(tenant_id), reply_id=str(reply_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 读取回复详情
        result = await db.execute(
            text("""
                SELECT id, platform, generated_reply, status
                FROM review_auto_replies
                WHERE id = :reply_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"reply_id": str(reply_id), "tenant_id": str(tenant_id)},
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"回复不存在: {reply_id}")

        if row[3] != "approved":
            raise ValueError(f"回复状态必须为approved才能发布，当前状态: {row[3]}")

        platform = row[1]
        now = datetime.now(tz=timezone.utc)

        # TODO: 接入各平台API实际发布回复
        # 目前为占位实现，直接标记为posted
        try:
            await self._post_to_platform(platform, str(row[2]), log)

            await db.execute(
                text("""
                    UPDATE review_auto_replies
                    SET status = 'posted',
                        posted_at = :posted_at,
                        updated_at = :updated_at
                    WHERE id = :reply_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "reply_id": str(reply_id),
                    "tenant_id": str(tenant_id),
                    "posted_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                },
            )
            await db.commit()

            log.info("review_replier.reply_posted", platform=platform)
            return {"reply_id": str(reply_id), "status": "posted", "platform": platform}

        except RuntimeError as exc:
            await db.execute(
                text("""
                    UPDATE review_auto_replies
                    SET status = 'failed',
                        failure_reason = :reason,
                        updated_at = :updated_at
                    WHERE id = :reply_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "reply_id": str(reply_id),
                    "tenant_id": str(tenant_id),
                    "reason": str(exc),
                    "updated_at": now.isoformat(),
                },
            )
            await db.commit()
            log.error("review_replier.post_failed", error=str(exc))
            raise

    async def get_brand_voice_config(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """读取品牌语调配置

        优先从brand_strategy表读取，无配置则返回默认值。
        """
        try:
            result = await db.execute(
                text("""
                    SELECT config_value
                    FROM brand_strategy
                    WHERE tenant_id = :tenant_id
                      AND config_key = 'brand_voice'
                      AND is_deleted = false
                    ORDER BY updated_at DESC
                    LIMIT 1
                """),
                {"tenant_id": str(tenant_id)},
            )
            row = result.fetchone()
            if row and row[0]:
                config = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                return config
        except Exception as exc:  # noqa: BLE001 — brand_strategy表可能不存在
            logger.debug("review_replier.brand_voice_fallback", error=str(exc))

        return dict(_DEFAULT_BRAND_VOICE)

    async def auto_generate_for_negative(
        self,
        tenant_id: uuid.UUID,
        min_rating: float,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """为所有评分<=min_rating且无回复的评论批量生成AI回复

        参数：
          - tenant_id: 租户ID
          - min_rating: 评分阈值（含），如3.0
          - db: 数据库会话

        返回批量生成结果摘要。
        """
        log = logger.bind(tenant_id=str(tenant_id), min_rating=min_rating)

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 查找需要回复的差评
        result = await db.execute(
            text("""
                SELECT r.id
                FROM order_reviews r
                LEFT JOIN review_auto_replies a
                    ON a.review_id = r.id
                    AND a.tenant_id = r.tenant_id
                    AND a.is_deleted = false
                WHERE r.tenant_id = :tenant_id
                  AND r.rating <= :min_rating
                  AND r.is_deleted = false
                  AND a.id IS NULL
                ORDER BY r.created_at DESC
                LIMIT 50
            """),
            {"tenant_id": str(tenant_id), "min_rating": min_rating},
        )
        rows = result.fetchall()

        if not rows:
            log.info("review_replier.no_negative_reviews_to_reply")
            return {"generated": 0, "failed": 0}

        brand_voice = await self.get_brand_voice_config(tenant_id, db)

        generated = 0
        failed = 0
        for row in rows:
            review_id = uuid.UUID(str(row[0]))
            try:
                await self.generate_reply(tenant_id, review_id, db, brand_voice)
                generated += 1
            except (ValueError, RuntimeError) as exc:
                log.warning(
                    "review_replier.batch_generate_failed",
                    review_id=str(review_id),
                    error=str(exc),
                )
                failed += 1

        log.info(
            "review_replier.batch_generate_done",
            total=len(rows),
            generated=generated,
            failed=failed,
        )
        return {"generated": generated, "failed": failed, "total_candidates": len(rows)}

    # ── 内部方法 ──

    async def _get_brand_name(self, tenant_id: uuid.UUID, db: AsyncSession) -> str:
        """从tenants表获取品牌名称"""
        try:
            result = await db.execute(
                text("""
                    SELECT name FROM tenants
                    WHERE id = :tenant_id AND is_deleted = false
                    LIMIT 1
                """),
                {"tenant_id": str(tenant_id)},
            )
            row = result.fetchone()
            if row:
                return str(row[0])
        except Exception as exc:  # noqa: BLE001 — tenants表结构可能不同
            logger.debug("review_replier.brand_name_fallback", error=str(exc))
        return "我们的餐厅"

    async def _call_ai_generate(self, prompt: str, log: Any) -> str:
        """调用tx-brain Claude API生成回复

        生产环境通过HTTP调用tx-brain :8010，
        此处为内置降级实现（适用于测试和离线场景）。
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "http://localhost:8010/api/v1/brain/complete",
                    json={
                        "model": "claude-haiku",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 200,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return str(data.get("data", {}).get("content", ""))
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            log.warning("review_replier.ai_call_failed_fallback", error=str(exc))

        # 降级：基于模板的简单回复
        return self._fallback_reply()

    def _fallback_reply(self) -> str:
        """AI不可用时的降级模板回复"""
        return (
            "感谢您的评价！我们非常重视您的反馈，"
            "已将您提到的问题反馈给相关团队进行改进。"
            "期待您的再次光临，我们一定会做得更好！"
        )

    async def _post_to_platform(self, platform: str, reply_text: str, log: Any) -> None:
        """发布回复到指定平台（占位实现）

        TODO: 接入各平台回复API
          - dianping: 大众点评商户API
          - meituan: 美团开放平台
          - douyin: 抖音本地生活API
          - google: Google Business Profile API
          - xiaohongshu: 小红书商家API
        """
        log.info(
            "review_replier.post_to_platform_placeholder",
            platform=platform,
            reply_length=len(reply_text),
        )
        # 占位：实际发布逻辑待接入平台SDK
