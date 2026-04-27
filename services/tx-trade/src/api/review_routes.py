"""顾客评价管理 API — 提交/查询/商家回复/统计"""

from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/reviews", tags=["reviews"])


class ReviewCreate(BaseModel):
    order_id: str
    overall_rating: int  # 1-5
    sub_ratings: dict  # {food: 4, service: 5, environment: 4, speed: 3}
    content: Optional[str] = None
    tags: List[str] = []
    image_urls: List[str] = []
    is_anonymous: bool = False


class MerchantReply(BaseModel):
    content: str


@router.get("")
async def list_reviews(
    store_id: Optional[str] = Query(None),
    rating_filter: Optional[int] = Query(None, description="1-5星筛选"),
    status: Optional[str] = Query(None),
    has_image: Optional[bool] = Query(None),
    replied: Optional[bool] = Query(None),
    page: int = Query(1),
    size: int = Query(20),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """评价列表（管理端）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        conditions = ["r.is_deleted = false"]
        params: dict = {}

        if store_id:
            conditions.append("r.store_id = :store_id::uuid")
            params["store_id"] = store_id
        if rating_filter:
            conditions.append("r.overall_rating = :rating_filter")
            params["rating_filter"] = rating_filter
        if status:
            conditions.append("r.status = :status")
            params["status"] = status
        if has_image is not None:
            # review_media joined — check existence
            if has_image:
                conditions.append("EXISTS (SELECT 1 FROM review_media m WHERE m.review_id = r.id)")
            else:
                conditions.append("NOT EXISTS (SELECT 1 FROM review_media m WHERE m.review_id = r.id)")
        if replied is not None:
            if replied:
                conditions.append("r.merchant_reply IS NOT NULL")
            else:
                conditions.append("r.merchant_reply IS NULL")

        where_clause = " AND ".join(conditions)
        offset = (page - 1) * size

        # Main query
        rows = (
            await db.execute(
                text(
                    f"""
                    SELECT
                        r.id::text,
                        r.order_id::text,
                        r.store_id::text,
                        r.customer_id::text,
                        r.overall_rating,
                        r.food_rating,
                        r.service_rating,
                        r.environment_rating,
                        r.speed_rating,
                        r.content,
                        r.tags,
                        r.is_anonymous,
                        r.status,
                        r.merchant_reply,
                        r.merchant_replied_at,
                        r.created_at
                    FROM order_reviews r
                    WHERE {where_clause}
                    ORDER BY r.created_at DESC
                    LIMIT :size OFFSET :offset
                    """
                ),
                {**params, "size": size, "offset": offset},
            )
        ).fetchall()

        # Count + aggregate stats (on full unfiltered tenant data for summary bar)
        stats_row = (
            await db.execute(
                text(
                    """
                    SELECT
                        COUNT(*)                                             AS total_filtered,
                        COUNT(*) FILTER (WHERE is_deleted = false)           AS total_all,
                        ROUND(AVG(overall_rating) FILTER (WHERE is_deleted = false), 1) AS avg_rating,
                        COUNT(*) FILTER (WHERE overall_rating >= 4 AND is_deleted = false) AS positive_count,
                        COUNT(*) FILTER (WHERE merchant_reply IS NULL AND is_deleted = false) AS unreplied_count
                    FROM order_reviews
                    WHERE is_deleted = false
                    """
                )
            )
        ).fetchone()

        items = []
        for row in rows:
            sub_ratings = {}
            if row.food_rating is not None:
                sub_ratings["food"] = row.food_rating
            if row.service_rating is not None:
                sub_ratings["service"] = row.service_rating
            if row.environment_rating is not None:
                sub_ratings["environment"] = row.environment_rating
            if row.speed_rating is not None:
                sub_ratings["speed"] = row.speed_rating

            items.append(
                {
                    "id": row.id,
                    "order_id": row.order_id,
                    "store_id": row.store_id,
                    "customer_id": row.customer_id,
                    "overall_rating": row.overall_rating,
                    "sub_ratings": sub_ratings,
                    "content": row.content,
                    "tags": row.tags or [],
                    "is_anonymous": row.is_anonymous,
                    "status": row.status,
                    "merchant_reply": row.merchant_reply,
                    "merchant_replied_at": (row.merchant_replied_at.isoformat() if row.merchant_replied_at else None),
                    "created_at": (row.created_at.isoformat() if row.created_at else None),
                }
            )

        total_all = stats_row.total_all or 0
        avg_rating = float(stats_row.avg_rating) if stats_row.avg_rating else 0.0
        positive_count = stats_row.positive_count or 0
        unreplied_count = stats_row.unreplied_count or 0
        positive_rate = round(positive_count / total_all * 100, 1) if total_all else 0.0

        # Count matching rows for pagination
        count_row = (
            await db.execute(
                text(f"SELECT COUNT(*) AS cnt FROM order_reviews r WHERE {where_clause}"),
                params,
            )
        ).fetchone()
        total_filtered = count_row.cnt if count_row else 0

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total_filtered,
                "avg_rating": avg_rating,
                "positive_rate": positive_rate,
                "unreplied_count": unreplied_count,
            },
        }

    except SQLAlchemyError as exc:
        log.error("review.list.db_error", error=str(exc))
        return {
            "ok": True,
            "data": {
                "items": [],
                "total": 0,
                "avg_rating": 0.0,
                "positive_rate": 0.0,
                "unreplied_count": 0,
                "_degraded": True,
            },
        }


@router.post("")
async def create_review(
    body: ReviewCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """顾客提交评价"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        status = "published" if body.overall_rating >= 3 else "pending_review"
        sub = body.sub_ratings

        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO order_reviews (
                        tenant_id, order_id,
                        overall_rating, food_rating, service_rating,
                        environment_rating, speed_rating,
                        content, tags, is_anonymous, status
                    ) VALUES (
                        :tenant_id::uuid, :order_id::uuid,
                        :overall_rating, :food_rating, :service_rating,
                        :environment_rating, :speed_rating,
                        :content, :tags::jsonb, :is_anonymous, :status
                    )
                    RETURNING id::text, order_id::text, overall_rating, status
                    """
                ),
                {
                    "tenant_id": x_tenant_id,
                    "order_id": body.order_id,
                    "overall_rating": body.overall_rating,
                    "food_rating": sub.get("food"),
                    "service_rating": sub.get("service"),
                    "environment_rating": sub.get("environment"),
                    "speed_rating": sub.get("speed"),
                    "content": body.content,
                    "tags": __import__("json").dumps(body.tags, ensure_ascii=False),
                    "is_anonymous": body.is_anonymous,
                    "status": status,
                },
            )
        ).fetchone()

        await db.commit()
        log.info(
            "review.create",
            review_id=row.id,
            rating=body.overall_rating,
            order_id=body.order_id,
        )
        return {
            "ok": True,
            "data": {
                "id": row.id,
                "order_id": row.order_id,
                "overall_rating": row.overall_rating,
                "status": row.status,
            },
        }

    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("review.create.db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="评价提交暂时不可用，请稍后重试")


@router.post("/{review_id}/reply")
async def merchant_reply(
    review_id: str,
    body: MerchantReply,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """商家回复评价"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        now = datetime.now(timezone.utc)
        result = await db.execute(
            text(
                """
                UPDATE order_reviews
                SET merchant_reply = :reply,
                    merchant_replied_at = :replied_at,
                    updated_at = :replied_at
                WHERE id = :review_id::uuid
                  AND is_deleted = false
                RETURNING id::text, merchant_reply, merchant_replied_at
                """
            ),
            {
                "reply": body.content,
                "replied_at": now,
                "review_id": review_id,
            },
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"评价不存在: {review_id}")

        await db.commit()
        log.info("review.reply", review_id=review_id)
        return {
            "ok": True,
            "data": {
                "id": row.id,
                "merchant_reply": row.merchant_reply,
                "merchant_replied_at": row.merchant_replied_at.isoformat(),
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("review.reply.db_error", review_id=review_id, error=str(exc))
        raise HTTPException(status_code=503, detail="回复暂时不可用，请稍后重试")


@router.post("/{review_id}/hide")
async def hide_review(
    review_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """隐藏/屏蔽评价（违规内容）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        result = await db.execute(
            text(
                """
                UPDATE order_reviews
                SET status = 'hidden', updated_at = NOW()
                WHERE id = :review_id::uuid
                  AND is_deleted = false
                RETURNING id::text, status
                """
            ),
            {"review_id": review_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"评价不存在: {review_id}")

        await db.commit()
        log.info("review.hide", review_id=review_id)
        return {"ok": True, "data": {"id": row.id, "status": row.status}}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("review.hide.db_error", review_id=review_id, error=str(exc))
        raise HTTPException(status_code=503, detail="操作暂时不可用，请稍后重试")


@router.get("/stats")
async def review_stats(
    days: int = Query(30),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """评价统计"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        stats_row = (
            await db.execute(
                text(
                    """
                    SELECT
                        COUNT(*)                                                    AS total_reviews,
                        ROUND(AVG(overall_rating), 1)                               AS avg_rating,
                        COUNT(*) FILTER (WHERE overall_rating = 5)                  AS cnt_5,
                        COUNT(*) FILTER (WHERE overall_rating = 4)                  AS cnt_4,
                        COUNT(*) FILTER (WHERE overall_rating = 3)                  AS cnt_3,
                        COUNT(*) FILTER (WHERE overall_rating = 2)                  AS cnt_2,
                        COUNT(*) FILTER (WHERE overall_rating = 1)                  AS cnt_1,
                        ROUND(AVG(food_rating), 1)                                  AS avg_food,
                        ROUND(AVG(service_rating), 1)                               AS avg_service,
                        ROUND(AVG(environment_rating), 1)                           AS avg_environment,
                        ROUND(AVG(speed_rating), 1)                                 AS avg_speed,
                        COUNT(*) FILTER (WHERE overall_rating >= 4)                 AS positive_count,
                        COUNT(*) FILTER (WHERE merchant_reply IS NULL)              AS unreplied_count
                    FROM order_reviews
                    WHERE is_deleted = false
                      AND created_at >= NOW() - (:days || ' days')::interval
                    """
                ),
                {"days": days},
            )
        ).fetchone()

        total = stats_row.total_reviews or 0
        avg_rating = float(stats_row.avg_rating) if stats_row.avg_rating else 0.0
        positive_rate = round(stats_row.positive_count / total * 100, 1) if total else 0.0

        # Top tags — unnest JSONB array of tags and count
        tag_rows = (
            await db.execute(
                text(
                    """
                    SELECT tag, COUNT(*) AS cnt
                    FROM order_reviews,
                         LATERAL jsonb_array_elements_text(COALESCE(tags, '[]'::jsonb)) AS t(tag)
                    WHERE is_deleted = false
                      AND created_at >= NOW() - (:days || ' days')::interval
                    GROUP BY tag
                    ORDER BY cnt DESC
                    LIMIT 10
                    """
                ),
                {"days": days},
            )
        ).fetchall()

        return {
            "ok": True,
            "data": {
                "avg_rating": avg_rating,
                "total_reviews": total,
                "rating_distribution": {
                    "5": stats_row.cnt_5 or 0,
                    "4": stats_row.cnt_4 or 0,
                    "3": stats_row.cnt_3 or 0,
                    "2": stats_row.cnt_2 or 0,
                    "1": stats_row.cnt_1 or 0,
                },
                "sub_rating_avg": {
                    "food": float(stats_row.avg_food) if stats_row.avg_food else 0.0,
                    "service": float(stats_row.avg_service) if stats_row.avg_service else 0.0,
                    "environment": float(stats_row.avg_environment) if stats_row.avg_environment else 0.0,
                    "speed": float(stats_row.avg_speed) if stats_row.avg_speed else 0.0,
                },
                "positive_rate": positive_rate,
                "unreplied_count": stats_row.unreplied_count or 0,
                "top_tags": [{"tag": row.tag, "count": row.cnt} for row in tag_rows],
            },
        }

    except SQLAlchemyError as exc:
        log.error("review.stats.db_error", error=str(exc))
        return {
            "ok": True,
            "data": {
                "avg_rating": 0.0,
                "total_reviews": 0,
                "rating_distribution": {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0},
                "sub_rating_avg": {"food": 0.0, "service": 0.0, "environment": 0.0, "speed": 0.0},
                "positive_rate": 0.0,
                "unreplied_count": 0,
                "top_tags": [],
                "_degraded": True,
            },
        }
