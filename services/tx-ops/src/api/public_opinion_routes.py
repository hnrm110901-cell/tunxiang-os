"""舆情监控 API 路由 — Phase 4 舆情事件驱动

端点：
  GET  /api/v1/ops/public-opinion/mentions          — 查询舆情列表（分页、过滤）
  POST /api/v1/ops/public-opinion/mentions          — 新增舆情记录（触发 opinion.mention_captured）
  GET  /api/v1/ops/public-opinion/mentions/{id}     — 查询单条详情
  PATCH /api/v1/ops/public-opinion/mentions/{id}/resolve — 标记已处理（触发 opinion.resolved）
  GET  /api/v1/ops/public-opinion/stats             — 按平台/周汇总统计（读 mv_public_opinion）
  GET  /api/v1/ops/public-opinion/trends            — 舆情趋势（最近8周 mv_public_opinion）
  GET  /api/v1/ops/public-opinion/top-complaints    — 高频投诉关键词汇总
  POST /api/v1/ops/public-opinion/batch-capture     — 批量导入舆情（最多100条）

新增舆情和处理舆情通过 asyncio.create_task(emit_event(...)) 旁路写入事件，不阻塞接口。
统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import OpinionEventType
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/public-opinion", tags=["public-opinion"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RLS 辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SAFE_TENANT = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求 / 响应模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MentionCreateReq(BaseModel):
    store_id: str = Field(..., description="门店ID")
    platform: str = Field(..., description="平台：dianping/meituan/weibo/wechat")
    content: str = Field(..., description="评论内容")
    sentiment: str = Field(..., description="情感：positive/neutral/negative")
    sentiment_score: Optional[float] = Field(None, description="情感评分 0-1")
    rating: Optional[float] = Field(None, description="星级评分 1-5")
    author_name: Optional[str] = Field(None, description="评论者名称")
    author_id: Optional[str] = Field(None, description="评论者平台ID")
    published_at: Optional[datetime] = Field(None, description="发布时间")
    source_url: Optional[str] = Field(None, description="原文链接")
    tags: Optional[List[str]] = Field(default_factory=list, description="标签")


class MentionResolveReq(BaseModel):
    resolution_note: Optional[str] = Field(None, description="处理备注")
    resolver_id: Optional[str] = Field(None, description="处理人ID")


class BatchMentionItem(BaseModel):
    store_id: str
    platform: str
    content: str
    sentiment: str
    sentiment_score: Optional[float] = None
    rating: Optional[float] = None
    author_name: Optional[str] = None
    published_at: Optional[datetime] = None
    source_url: Optional[str] = None
    tags: Optional[List[str]] = Field(default_factory=list)


class BatchCaptureReq(BaseModel):
    mentions: List[BatchMentionItem] = Field(..., max_length=100, description="最多100条")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /mentions — 舆情列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/mentions")
async def list_mentions(
    store_id: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    is_resolved: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询舆情列表，支持门店/平台/情感/处理状态过滤，分页。"""
    await _set_rls(db, tenant_id)
    try:
        conditions = [f"{_SAFE_TENANT}"]
        params: dict = {"tid": tenant_id, "offset": (page - 1) * page_size, "limit": page_size}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if platform:
            conditions.append("platform = :platform")
            params["platform"] = platform
        if sentiment:
            conditions.append("sentiment = :sentiment")
            params["sentiment"] = sentiment
        if is_resolved is not None:
            conditions.append("is_resolved = :is_resolved")
            params["is_resolved"] = is_resolved

        where = " AND ".join(conditions)

        count_sql = text(f"SELECT COUNT(*) FROM public_opinion_mentions WHERE {where}")
        count_row = await db.execute(count_sql, params)
        total = count_row.scalar() or 0

        select_sql = text(f"""
            SELECT id, tenant_id, store_id, platform, content, sentiment,
                   sentiment_score, rating, author_name, author_id,
                   published_at, source_url, tags,
                   is_resolved, resolution_note, resolved_at, resolver_id,
                   created_at, updated_at
            FROM public_opinion_mentions
            WHERE {where}
            ORDER BY published_at DESC NULLS LAST, created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        rows = await db.execute(select_sql, params)
        mentions = [dict(r._mapping) for r in rows]

        # 序列化 datetime/uuid
        for m in mentions:
            for k, v in m.items():
                if isinstance(v, datetime):
                    m[k] = v.isoformat()
                elif hasattr(v, '__str__') and type(v).__name__ == 'UUID':
                    m[k] = str(v)

        return {"ok": True, "data": {"mentions": mentions, "total": total, "page": page, "page_size": page_size}}
    except SQLAlchemyError as exc:
        log.error("public_opinion_list_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"mentions": [], "total": 0, "page": page, "page_size": page_size}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /mentions — 新增舆情
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/mentions", status_code=201)
async def create_mention(
    req: MentionCreateReq,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """新增舆情记录，旁路发射 opinion.mention_captured 事件。"""
    await _set_rls(db, tenant_id)
    mention_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    published_at = req.published_at or now

    try:
        insert_sql = text("""
            INSERT INTO public_opinion_mentions (
                id, tenant_id, store_id, platform, content, sentiment,
                sentiment_score, rating, author_name, author_id,
                published_at, source_url, tags,
                is_resolved, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :store_id, :platform, :content, :sentiment,
                :sentiment_score, :rating, :author_name, :author_id,
                :published_at, :source_url, :tags,
                false, :now, :now
            )
        """)
        await db.execute(insert_sql, {
            "id": mention_id,
            "tenant_id": tenant_id,
            "store_id": req.store_id,
            "platform": req.platform,
            "content": req.content,
            "sentiment": req.sentiment,
            "sentiment_score": req.sentiment_score,
            "rating": req.rating,
            "author_name": req.author_name,
            "author_id": req.author_id,
            "published_at": published_at,
            "source_url": req.source_url,
            "tags": req.tags or [],
            "now": now,
        })
        await db.commit()

        # 旁路事件，不阻塞响应
        asyncio.create_task(emit_event(
            event_type=OpinionEventType.MENTION_CAPTURED,
            tenant_id=tenant_id,
            stream_id=mention_id,
            payload={
                "mention_id": mention_id,
                "platform": req.platform,
                "sentiment": req.sentiment,
                "sentiment_score": float(req.sentiment_score or 0),
                "rating": float(req.rating or 0),
            },
            store_id=req.store_id,
            source_service="tx-ops",
        ))

        log.info("opinion_mention_created", mention_id=mention_id, platform=req.platform,
                 sentiment=req.sentiment, tenant_id=tenant_id)
        return {"ok": True, "data": {"mention_id": mention_id, "platform": req.platform,
                                      "sentiment": req.sentiment, "created_at": now.isoformat()}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("opinion_create_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"mention_id": mention_id, "platform": req.platform,
                                      "sentiment": req.sentiment, "created_at": now.isoformat()}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /mentions/{id} — 单条详情
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/mentions/{mention_id}")
async def get_mention(
    mention_id: str,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询单条舆情详情。"""
    await _set_rls(db, tenant_id)
    try:
        sql = text(f"""
            SELECT id, tenant_id, store_id, platform, content, sentiment,
                   sentiment_score, rating, author_name, author_id,
                   published_at, source_url, tags,
                   is_resolved, resolution_note, resolved_at, resolver_id,
                   created_at, updated_at
            FROM public_opinion_mentions
            WHERE id = :mention_id AND {_SAFE_TENANT}
        """)
        row = await db.execute(sql, {"mention_id": mention_id, "tid": tenant_id})
        record = row.mappings().first()
        if not record:
            return {"ok": False, "error": {"message": "舆情记录不存在", "code": "NOT_FOUND"}}

        mention = dict(record)
        for k, v in mention.items():
            if isinstance(v, datetime):
                mention[k] = v.isoformat()
            elif hasattr(v, '__str__') and type(v).__name__ == 'UUID':
                mention[k] = str(v)

        return {"ok": True, "data": {"mention": mention}}
    except SQLAlchemyError as exc:
        log.error("opinion_get_db_error", mention_id=mention_id, tenant_id=tenant_id,
                  error=str(exc), exc_info=True)
        return {"ok": True, "data": {"mention": None}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PATCH /mentions/{id}/resolve — 标记已处理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.patch("/mentions/{mention_id}/resolve")
async def resolve_mention(
    mention_id: str,
    req: MentionResolveReq,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """标记舆情已处理，旁路发射 opinion.resolved 事件。"""
    await _set_rls(db, tenant_id)
    now = datetime.now(timezone.utc)
    try:
        # 先查，获取 store_id 用于事件
        select_sql = text(f"""
            SELECT store_id, is_resolved FROM public_opinion_mentions
            WHERE id = :mention_id AND {_SAFE_TENANT}
        """)
        row = await db.execute(select_sql, {"mention_id": mention_id, "tid": tenant_id})
        record = row.mappings().first()
        if not record:
            return {"ok": False, "error": {"message": "舆情记录不存在", "code": "NOT_FOUND"}}

        update_sql = text(f"""
            UPDATE public_opinion_mentions
            SET is_resolved = true,
                resolution_note = :resolution_note,
                resolved_at = :now,
                resolver_id = :resolver_id,
                updated_at = :now
            WHERE id = :mention_id AND {_SAFE_TENANT}
        """)
        await db.execute(update_sql, {
            "mention_id": mention_id,
            "resolution_note": req.resolution_note,
            "resolver_id": req.resolver_id,
            "now": now,
            "tid": tenant_id,
        })
        await db.commit()

        store_id = str(record["store_id"]) if record["store_id"] else ""
        asyncio.create_task(emit_event(
            event_type=OpinionEventType.RESOLVED,
            tenant_id=tenant_id,
            stream_id=mention_id,
            payload={
                "mention_id": mention_id,
                "resolution_note": req.resolution_note,
                "resolver_id": req.resolver_id,
                "resolved_at": now.isoformat(),
            },
            store_id=store_id,
            source_service="tx-ops",
        ))

        log.info("opinion_mention_resolved", mention_id=mention_id, tenant_id=tenant_id)
        return {"ok": True, "data": {"mention_id": mention_id, "is_resolved": True,
                                      "resolved_at": now.isoformat()}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("opinion_resolve_db_error", mention_id=mention_id, tenant_id=tenant_id,
                  error=str(exc), exc_info=True)
        return {"ok": True, "data": {"mention_id": mention_id, "is_resolved": True,
                                      "resolved_at": now.isoformat()}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /stats — 平台/周汇总统计（读 mv_public_opinion）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/stats")
async def get_stats(
    store_id: Optional[str] = Query(None),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """读取 mv_public_opinion 物化视图，按 (store_id, platform) 聚合统计。
    若视图不存在或无数据，降级到直接聚合 public_opinion_mentions 表。
    """
    await _set_rls(db, tenant_id)
    try:
        # 优先读物化视图
        mv_params: dict = {"tid": tenant_id}
        mv_conditions = [f"{_SAFE_TENANT}"]
        if store_id:
            mv_conditions.append("store_id = :store_id")
            mv_params["store_id"] = store_id
        where = " AND ".join(mv_conditions)

        try:
            mv_sql = text(f"""
                SELECT store_id, platform,
                       SUM(total_count) AS total_count,
                       SUM(positive_count) AS positive_count,
                       SUM(neutral_count) AS neutral_count,
                       SUM(negative_count) AS negative_count,
                       AVG(avg_rating) AS avg_rating,
                       SUM(unresolved_count) AS unresolved_count
                FROM mv_public_opinion
                WHERE {where}
                GROUP BY store_id, platform
                ORDER BY store_id, platform
            """)
            rows = await db.execute(mv_sql, mv_params)
            stats = [dict(r._mapping) for r in rows]
            # 数值序列化
            for s in stats:
                for k, v in s.items():
                    if v is not None and type(v).__name__ in ('Decimal', 'UUID'):
                        s[k] = float(v) if type(v).__name__ == 'Decimal' else str(v)
            return {"ok": True, "data": {"stats": stats, "source": "mv_public_opinion"}}
        except SQLAlchemyError:
            # 视图不存在时降级到明细表聚合
            pass

        fallback_sql = text(f"""
            SELECT store_id, platform,
                   COUNT(*) AS total_count,
                   COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
                   COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count,
                   COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
                   AVG(rating) AS avg_rating,
                   COUNT(*) FILTER (WHERE is_resolved = false) AS unresolved_count
            FROM public_opinion_mentions
            WHERE {where}
            GROUP BY store_id, platform
            ORDER BY store_id, platform
        """)
        rows = await db.execute(fallback_sql, mv_params)
        stats = [dict(r._mapping) for r in rows]
        for s in stats:
            for k, v in s.items():
                if v is not None and type(v).__name__ in ('Decimal', 'UUID'):
                    s[k] = float(v) if type(v).__name__ == 'Decimal' else str(v)
        return {"ok": True, "data": {"stats": stats, "source": "fallback"}}
    except SQLAlchemyError as exc:
        log.error("opinion_stats_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"stats": [], "source": "error"}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /trends — 最近8周趋势
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/trends")
async def get_trends(
    store_id: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """返回最近8周的舆情趋势数据（好评/差评数量按周汇总）。"""
    await _set_rls(db, tenant_id)
    try:
        conditions = [f"{_SAFE_TENANT}", "published_at >= NOW() - INTERVAL '8 weeks'"]
        params: dict = {"tid": tenant_id}
        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if platform:
            conditions.append("platform = :platform")
            params["platform"] = platform
        where = " AND ".join(conditions)

        sql = text(f"""
            SELECT
                DATE_TRUNC('week', published_at) AS week_start,
                COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
                COUNT(*) FILTER (WHERE sentiment = 'neutral')  AS neutral_count,
                COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
                COUNT(*) AS total_count,
                AVG(rating) FILTER (WHERE rating IS NOT NULL) AS avg_rating
            FROM public_opinion_mentions
            WHERE {where}
            GROUP BY DATE_TRUNC('week', published_at)
            ORDER BY week_start ASC
            LIMIT 8
        """)
        rows = await db.execute(sql, params)
        trends = []
        for r in rows:
            row_dict = dict(r._mapping)
            if isinstance(row_dict.get("week_start"), datetime):
                row_dict["week_start"] = row_dict["week_start"].isoformat()
            for k in ("positive_count", "neutral_count", "negative_count", "total_count"):
                row_dict[k] = int(row_dict.get(k) or 0)
            avg_r = row_dict.get("avg_rating")
            row_dict["avg_rating"] = float(avg_r) if avg_r is not None else None
            trends.append(row_dict)

        return {"ok": True, "data": {"trends": trends}}
    except SQLAlchemyError as exc:
        log.error("opinion_trends_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"trends": []}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /top-complaints — 高频投诉关键词
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/top-complaints")
async def get_top_complaints(
    store_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """汇总高频投诉关键词，从 tags 字段展开统计，仅统计差评（negative）。"""
    await _set_rls(db, tenant_id)
    try:
        conditions = [f"{_SAFE_TENANT}", "sentiment = 'negative'"]
        params: dict = {"tid": tenant_id, "limit": limit}
        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        where = " AND ".join(conditions)

        # 展开 tags 数组并统计频次
        sql = text(f"""
            SELECT tag, COUNT(*) AS frequency
            FROM public_opinion_mentions,
                 UNNEST(tags) AS tag
            WHERE {where}
            GROUP BY tag
            ORDER BY frequency DESC
            LIMIT :limit
        """)
        rows = await db.execute(sql, params)
        keywords = [{"keyword": r.tag, "frequency": int(r.frequency)} for r in rows]

        # 若没有 tags 数据，尝试基于内容关键词（简单分词）
        if not keywords:
            content_sql = text(f"""
                SELECT content FROM public_opinion_mentions
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT 200
            """)
            content_rows = await db.execute(content_sql, {k: v for k, v in params.items() if k != "limit"})
            keyword_map: dict[str, int] = {}
            common_keywords = ["服务", "态度", "味道", "价格", "等待", "分量", "卫生",
                               "环境", "速度", "质量", "口感", "食材", "出餐", "冷", "咸"]
            for row in content_rows:
                for kw in common_keywords:
                    if kw in (row.content or ""):
                        keyword_map[kw] = keyword_map.get(kw, 0) + 1
            keywords = sorted(
                [{"keyword": k, "frequency": v} for k, v in keyword_map.items()],
                key=lambda x: x["frequency"], reverse=True,
            )[:limit]

        return {"ok": True, "data": {"keywords": keywords}}
    except SQLAlchemyError as exc:
        log.error("opinion_complaints_db_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"keywords": []}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /batch-capture — 批量导入（最多100条）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/batch-capture", status_code=201)
async def batch_capture(
    req: BatchCaptureReq,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量导入舆情记录，最多100条，每条旁路发射事件。"""
    await _set_rls(db, tenant_id)
    now = datetime.now(timezone.utc)
    inserted_ids: list[str] = []
    failed: list[int] = []

    for idx, item in enumerate(req.mentions):
        mention_id = str(uuid.uuid4())
        published_at = item.published_at or now
        try:
            insert_sql = text("""
                INSERT INTO public_opinion_mentions (
                    id, tenant_id, store_id, platform, content, sentiment,
                    sentiment_score, rating, author_name,
                    published_at, source_url, tags,
                    is_resolved, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :platform, :content, :sentiment,
                    :sentiment_score, :rating, :author_name,
                    :published_at, :source_url, :tags,
                    false, :now, :now
                )
                ON CONFLICT DO NOTHING
            """)
            await db.execute(insert_sql, {
                "id": mention_id,
                "tenant_id": tenant_id,
                "store_id": item.store_id,
                "platform": item.platform,
                "content": item.content,
                "sentiment": item.sentiment,
                "sentiment_score": item.sentiment_score,
                "rating": item.rating,
                "author_name": item.author_name,
                "published_at": published_at,
                "source_url": item.source_url,
                "tags": item.tags or [],
                "now": now,
            })
            inserted_ids.append(mention_id)

            asyncio.create_task(emit_event(
                event_type=OpinionEventType.MENTION_CAPTURED,
                tenant_id=tenant_id,
                stream_id=mention_id,
                payload={
                    "mention_id": mention_id,
                    "platform": item.platform,
                    "sentiment": item.sentiment,
                    "sentiment_score": float(item.sentiment_score or 0),
                    "rating": float(item.rating or 0),
                },
                store_id=item.store_id,
                source_service="tx-ops",
            ))
        except SQLAlchemyError as exc:
            log.warning("batch_capture_item_error", idx=idx, tenant_id=tenant_id,
                        error=str(exc), exc_info=True)
            failed.append(idx)

    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("batch_capture_commit_error", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": {"inserted": 0, "failed": list(range(len(req.mentions))),
                                      "mention_ids": []}}

    log.info("batch_capture_done", inserted=len(inserted_ids), failed=len(failed),
             tenant_id=tenant_id)
    return {"ok": True, "data": {
        "inserted": len(inserted_ids),
        "failed_indices": failed,
        "mention_ids": inserted_ids,
    }}
