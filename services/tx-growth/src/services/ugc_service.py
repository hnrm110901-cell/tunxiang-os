"""UGC投稿服务 — 顾客照片/视频投稿 + AI审核 + 发布管理

核心流程：
  1. 顾客提交UGC（submit） → 状态 pending_review
  2. AI自动审核（photo_reviewer） → 高分自动通过 / 低分人工审核
  3. 管理员审批（approve/reject） → approved / rejected
  4. 发布到门店图墙（approve自动publish） → published
  5. 编辑精选（feature） → featured = true

积分规则：
  - 通过审核：+50积分
  - 编辑精选：额外+100积分

金额单位：分(fen)
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 积分配置
# ---------------------------------------------------------------------------

POINTS_APPROVED: int = 50
POINTS_FEATURED: int = 100


# ---------------------------------------------------------------------------
# 内部异常
# ---------------------------------------------------------------------------


class UGCError(Exception):
    """UGC业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# UGCService
# ---------------------------------------------------------------------------


class UGCService:
    """UGC投稿核心服务"""

    # ------------------------------------------------------------------
    # 提交UGC
    # ------------------------------------------------------------------

    async def submit(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        store_id: uuid.UUID,
        media_urls: list[dict],
        caption: str,
        db: Any,
        *,
        order_id: Optional[uuid.UUID] = None,
        dish_ids: Optional[list[str]] = None,
    ) -> dict:
        """顾客提交UGC内容（照片/视频+文案）

        Args:
            tenant_id: 租户ID
            customer_id: 顾客ID
            store_id: 门店ID
            media_urls: 媒体列表 [{url, type:'photo'|'video', thumbnail_url}]
            caption: 文案
            db: AsyncSession
            order_id: 关联订单ID（可选）
            dish_ids: 标记的菜品ID列表（可选）

        Returns:
            {ugc_id, status}
        """
        if not media_urls:
            raise UGCError("EMPTY_MEDIA", "至少需要上传一张照片或视频")

        ugc_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await db.execute(
            text("""
                INSERT INTO ugc_submissions (
                    id, tenant_id, customer_id, order_id, store_id,
                    media_urls, caption, dish_ids,
                    status, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :customer_id, :order_id, :store_id,
                    :media_urls::jsonb, :caption, :dish_ids::jsonb,
                    'pending_review', :now, :now
                )
            """),
            {
                "id": str(ugc_id),
                "tenant_id": str(tenant_id),
                "customer_id": str(customer_id),
                "order_id": str(order_id) if order_id else None,
                "store_id": str(store_id),
                "media_urls": json.dumps(media_urls),
                "caption": caption or "",
                "dish_ids": json.dumps(dish_ids or []),
                "now": now,
            },
        )
        await db.commit()

        log.info(
            "ugc.submitted",
            ugc_id=str(ugc_id),
            customer_id=str(customer_id),
            store_id=str(store_id),
            media_count=len(media_urls),
            tenant_id=str(tenant_id),
        )

        return {"ugc_id": str(ugc_id), "status": "pending_review"}

    # ------------------------------------------------------------------
    # 管理员审批通过
    # ------------------------------------------------------------------

    async def approve(
        self,
        tenant_id: uuid.UUID,
        ugc_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """审批通过UGC，自动发布并奖励积分

        Returns:
            {ugc_id, status, points_awarded}
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                UPDATE ugc_submissions
                SET status = 'published',
                    points_awarded = :points,
                    published_at = :now,
                    updated_at = :now
                WHERE id = :ugc_id
                  AND tenant_id = :tenant_id
                  AND status IN ('pending_review', 'approved')
                  AND is_deleted = false
                RETURNING id, customer_id, points_awarded
            """),
            {
                "ugc_id": str(ugc_id),
                "tenant_id": str(tenant_id),
                "points": POINTS_APPROVED,
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise UGCError("UGC_NOT_FOUND", "UGC不存在或状态不允许审批")

        await db.commit()

        log.info(
            "ugc.approved",
            ugc_id=str(ugc_id),
            customer_id=str(row.customer_id),
            points_awarded=POINTS_APPROVED,
            tenant_id=str(tenant_id),
        )

        return {
            "ugc_id": str(ugc_id),
            "status": "published",
            "points_awarded": POINTS_APPROVED,
        }

    # ------------------------------------------------------------------
    # 管理员拒绝
    # ------------------------------------------------------------------

    async def reject(
        self,
        tenant_id: uuid.UUID,
        ugc_id: uuid.UUID,
        reason: str,
        db: Any,
    ) -> dict:
        """拒绝UGC投稿

        Returns:
            {ugc_id, status, rejection_reason}
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                UPDATE ugc_submissions
                SET status = 'rejected',
                    rejection_reason = :reason,
                    updated_at = :now
                WHERE id = :ugc_id
                  AND tenant_id = :tenant_id
                  AND status = 'pending_review'
                  AND is_deleted = false
                RETURNING id
            """),
            {
                "ugc_id": str(ugc_id),
                "tenant_id": str(tenant_id),
                "reason": reason,
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise UGCError("UGC_NOT_FOUND", "UGC不存在或状态不允许拒绝")

        await db.commit()

        log.info(
            "ugc.rejected",
            ugc_id=str(ugc_id),
            reason=reason,
            tenant_id=str(tenant_id),
        )

        return {
            "ugc_id": str(ugc_id),
            "status": "rejected",
            "rejection_reason": reason,
        }

    # ------------------------------------------------------------------
    # 门店图墙（公开画廊）
    # ------------------------------------------------------------------

    async def get_gallery(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        db: Any,
        *,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """获取门店已发布UGC列表（图墙）

        Returns:
            {items: [...], total: int}
        """
        offset = (page - 1) * size

        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM ugc_submissions
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND status = 'published'
                  AND is_deleted = false
            """),
            {"tenant_id": str(tenant_id), "store_id": str(store_id)},
        )
        total: int = count_result.scalar_one()

        result = await db.execute(
            text("""
                SELECT id, customer_id, media_urls, caption, dish_ids,
                       ai_quality_score, points_awarded,
                       view_count, like_count, share_count,
                       featured, published_at, created_at
                FROM ugc_submissions
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND status = 'published'
                  AND is_deleted = false
                ORDER BY featured DESC, published_at DESC
                LIMIT :size OFFSET :offset
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "size": size,
                "offset": offset,
            },
        )
        rows = result.fetchall()

        items = [
            {
                "ugc_id": str(r.id),
                "customer_id": str(r.customer_id),
                "media_urls": r.media_urls,
                "caption": r.caption,
                "dish_ids": r.dish_ids,
                "ai_quality_score": r.ai_quality_score,
                "points_awarded": r.points_awarded,
                "view_count": r.view_count,
                "like_count": r.like_count,
                "share_count": r.share_count,
                "featured": r.featured,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

        return {"items": items, "total": total}

    # ------------------------------------------------------------------
    # 我的投稿
    # ------------------------------------------------------------------

    async def get_my_submissions(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        db: Any,
    ) -> list[dict]:
        """获取顾客自己的UGC投稿历史"""
        result = await db.execute(
            text("""
                SELECT id, store_id, media_urls, caption, dish_ids,
                       ai_quality_score, ai_quality_feedback,
                       status, rejection_reason, points_awarded,
                       view_count, like_count, share_count,
                       featured, published_at, created_at
                FROM ugc_submissions
                WHERE tenant_id = :tenant_id
                  AND customer_id = :customer_id
                  AND is_deleted = false
                ORDER BY created_at DESC
            """),
            {"tenant_id": str(tenant_id), "customer_id": str(customer_id)},
        )
        rows = result.fetchall()

        return [
            {
                "ugc_id": str(r.id),
                "store_id": str(r.store_id),
                "media_urls": r.media_urls,
                "caption": r.caption,
                "status": r.status,
                "rejection_reason": r.rejection_reason,
                "points_awarded": r.points_awarded,
                "view_count": r.view_count,
                "like_count": r.like_count,
                "share_count": r.share_count,
                "featured": r.featured,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 编辑精选
    # ------------------------------------------------------------------

    async def feature(
        self,
        tenant_id: uuid.UUID,
        ugc_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """标记为编辑精选，额外奖励积分

        Returns:
            {ugc_id, featured, extra_points}
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                UPDATE ugc_submissions
                SET featured = true,
                    points_awarded = points_awarded + :extra_points,
                    updated_at = :now
                WHERE id = :ugc_id
                  AND tenant_id = :tenant_id
                  AND status = 'published'
                  AND featured = false
                  AND is_deleted = false
                RETURNING id, customer_id, points_awarded
            """),
            {
                "ugc_id": str(ugc_id),
                "tenant_id": str(tenant_id),
                "extra_points": POINTS_FEATURED,
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise UGCError("UGC_NOT_FOUND", "UGC不存在或已被精选")

        await db.commit()

        log.info(
            "ugc.featured",
            ugc_id=str(ugc_id),
            customer_id=str(row.customer_id),
            total_points=row.points_awarded,
            tenant_id=str(tenant_id),
        )

        return {
            "ugc_id": str(ugc_id),
            "featured": True,
            "extra_points": POINTS_FEATURED,
        }

    # ------------------------------------------------------------------
    # 互动计数
    # ------------------------------------------------------------------

    async def increment_view(
        self,
        tenant_id: uuid.UUID,
        ugc_id: uuid.UUID,
        db: Any,
    ) -> None:
        """浏览量+1"""
        await db.execute(
            text("""
                UPDATE ugc_submissions
                SET view_count = view_count + 1,
                    updated_at = NOW()
                WHERE id = :ugc_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"ugc_id": str(ugc_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()

    async def increment_like(
        self,
        tenant_id: uuid.UUID,
        ugc_id: uuid.UUID,
        db: Any,
    ) -> None:
        """点赞量+1"""
        await db.execute(
            text("""
                UPDATE ugc_submissions
                SET like_count = like_count + 1,
                    updated_at = NOW()
                WHERE id = :ugc_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"ugc_id": str(ugc_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()
