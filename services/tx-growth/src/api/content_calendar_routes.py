"""内容日历 API — 7个端点（S3W11-12 Smart Content Factory）

端点:
1. GET    /api/v1/growth/content-calendar            内容列表（分页/过滤）
2. POST   /api/v1/growth/content-calendar            创建内容条目
3. PUT    /api/v1/growth/content-calendar/{id}       更新内容条目
4. DELETE /api/v1/growth/content-calendar/{id}       软删除
5. POST   /api/v1/growth/content-calendar/auto-generate  AI自动生成
6. POST   /api/v1/growth/content-calendar/{id}/schedule  设置排期
7. POST   /api/v1/growth/content-calendar/{id}/publish   立即发布
8. GET    /api/v1/growth/content-calendar/calendar-view  日历视图
"""

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.content_factory import ContentFactory
from ..services.poster_generator import PosterGenerator
from ..workers.content_publisher import ContentPublisher

router = APIRouter(prefix="/api/v1/growth/content-calendar", tags=["content-calendar"])

_factory = ContentFactory()
_poster = PosterGenerator()
_publisher = ContentPublisher()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreateContentRequest(BaseModel):
    title: str
    content_type: str
    content_body: str
    store_id: Optional[str] = None
    media_urls: list[dict] = []
    target_channels: list[dict] = []
    tags: list[str] = []
    ai_generated: bool = False
    ai_model: Optional[str] = None
    ai_prompt_context: dict = {}
    scheduled_at: Optional[str] = None
    created_by: Optional[str] = None


class UpdateContentRequest(BaseModel):
    title: Optional[str] = None
    content_type: Optional[str] = None
    content_body: Optional[str] = None
    store_id: Optional[str] = None
    media_urls: Optional[list[dict]] = None
    target_channels: Optional[list[dict]] = None
    tags: Optional[list[str]] = None
    scheduled_at: Optional[str] = None


class AutoGenerateRequest(BaseModel):
    mode: str = "auto"  # auto | dish | holiday | weekly_plan
    target_channel: str = "moments"
    dish_id: Optional[str] = None
    dish_ids: list[str] = []
    holiday: Optional[str] = None
    event_name: Optional[str] = None
    season: Optional[str] = None
    brand_voice: Optional[str] = None
    custom_prompt: Optional[str] = None
    store_id: Optional[str] = None
    channels: list[str] = []


class ScheduleRequest(BaseModel):
    scheduled_at: str


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.get("")
async def list_content(
    status: Optional[str] = Query(None),
    content_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """内容日历列表（分页/过滤）"""
    await _set_tenant(db, x_tenant_id)

    conditions = ["tenant_id = :tid", "is_deleted = false"]
    params: dict[str, Any] = {"tid": x_tenant_id}

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if content_type:
        conditions.append("content_type = :ctype")
        params["ctype"] = content_type
    if date_from:
        conditions.append("scheduled_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("scheduled_at <= :date_to")
        params["date_to"] = date_to

    where = " AND ".join(conditions)

    # Count
    count_row = await db.execute(
        text(f"SELECT COUNT(*) AS cnt FROM content_calendar WHERE {where}"),
        params,
    )
    total = count_row.scalar() or 0

    # Items
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset
    rows = await db.execute(
        text(f"""
            SELECT id, store_id, title, content_type, content_body,
                   media_urls, target_channels, tags, ai_generated, ai_model,
                   status, scheduled_at, published_at, created_by,
                   approved_by, approved_at,
                   view_count, click_count, share_count,
                   created_at, updated_at
            FROM content_calendar
            WHERE {where}
            ORDER BY COALESCE(scheduled_at, created_at) DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = []
    for r in rows.mappings().all():
        items.append(
            {
                "id": str(r["id"]),
                "store_id": str(r["store_id"]) if r["store_id"] else None,
                "title": r["title"],
                "content_type": r["content_type"],
                "content_body": r["content_body"],
                "media_urls": r["media_urls"],
                "target_channels": r["target_channels"],
                "tags": r["tags"],
                "ai_generated": r["ai_generated"],
                "ai_model": r["ai_model"],
                "status": r["status"],
                "scheduled_at": r["scheduled_at"].isoformat() if r["scheduled_at"] else None,
                "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                "created_by": str(r["created_by"]) if r["created_by"] else None,
                "approved_by": str(r["approved_by"]) if r["approved_by"] else None,
                "approved_at": r["approved_at"].isoformat() if r["approved_at"] else None,
                "view_count": r["view_count"],
                "click_count": r["click_count"],
                "share_count": r["share_count"],
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
        )

    return ok_response({"items": items, "total": total})


@router.post("")
async def create_content(
    req: CreateContentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建内容条目"""
    await _set_tenant(db, x_tenant_id)

    media_json = json.dumps(req.media_urls, ensure_ascii=False)
    channels_json = json.dumps(req.target_channels, ensure_ascii=False)
    tags_json = json.dumps(req.tags, ensure_ascii=False)
    ctx_json = json.dumps(req.ai_prompt_context, ensure_ascii=False)

    row = await db.execute(
        text("""
            INSERT INTO content_calendar
                (tenant_id, store_id, title, content_type, content_body,
                 media_urls, target_channels, tags, ai_generated, ai_model,
                 ai_prompt_context, scheduled_at, created_by, status)
            VALUES
                (:tid, :store_id, :title, :ctype, :body,
                 :media::jsonb, :channels::jsonb, :tags::jsonb, :ai_gen, :ai_model,
                 :ctx::jsonb, :sched, :created_by,
                 CASE WHEN :sched IS NOT NULL THEN 'scheduled' ELSE 'draft' END)
            RETURNING id, status, created_at
        """),
        {
            "tid": x_tenant_id,
            "store_id": req.store_id,
            "title": req.title,
            "ctype": req.content_type,
            "body": req.content_body,
            "media": media_json,
            "channels": channels_json,
            "tags": tags_json,
            "ai_gen": req.ai_generated,
            "ai_model": req.ai_model,
            "ctx": ctx_json,
            "sched": req.scheduled_at,
            "created_by": req.created_by,
        },
    )
    r = row.mappings().first()
    await db.commit()

    return ok_response(
        {
            "id": str(r["id"]),
            "status": r["status"],
            "created_at": r["created_at"].isoformat(),
        }
    )


@router.put("/{content_id}")
async def update_content(
    content_id: str,
    req: UpdateContentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新内容条目"""
    await _set_tenant(db, x_tenant_id)

    sets: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"cid": content_id, "tid": x_tenant_id}

    if req.title is not None:
        sets.append("title = :title")
        params["title"] = req.title
    if req.content_type is not None:
        sets.append("content_type = :ctype")
        params["ctype"] = req.content_type
    if req.content_body is not None:
        sets.append("content_body = :body")
        params["body"] = req.content_body
    if req.store_id is not None:
        sets.append("store_id = :store_id")
        params["store_id"] = req.store_id
    if req.media_urls is not None:
        sets.append("media_urls = :media::jsonb")
        params["media"] = json.dumps(req.media_urls, ensure_ascii=False)
    if req.target_channels is not None:
        sets.append("target_channels = :channels::jsonb")
        params["channels"] = json.dumps(req.target_channels, ensure_ascii=False)
    if req.tags is not None:
        sets.append("tags = :tags::jsonb")
        params["tags"] = json.dumps(req.tags, ensure_ascii=False)
    if req.scheduled_at is not None:
        sets.append("scheduled_at = :sched")
        params["sched"] = req.scheduled_at

    set_clause = ", ".join(sets)
    row = await db.execute(
        text(f"""
            UPDATE content_calendar
            SET {set_clause}
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
            RETURNING id, title, status, updated_at
        """),
        params,
    )
    r = row.mappings().first()
    if not r:
        return error_response("content_not_found")
    await db.commit()

    return ok_response(
        {
            "id": str(r["id"]),
            "title": r["title"],
            "status": r["status"],
            "updated_at": r["updated_at"].isoformat(),
        }
    )


@router.delete("/{content_id}")
async def delete_content(
    content_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """软删除内容条目"""
    await _set_tenant(db, x_tenant_id)

    row = await db.execute(
        text("""
            UPDATE content_calendar
            SET is_deleted = true, updated_at = NOW()
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
            RETURNING id
        """),
        {"cid": content_id, "tid": x_tenant_id},
    )
    r = row.mappings().first()
    if not r:
        return error_response("content_not_found")
    await db.commit()

    return ok_response({"id": str(r["id"]), "deleted": True})


@router.post("/auto-generate")
async def auto_generate_content(
    req: AutoGenerateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """AI自动生成内容"""
    if req.mode == "dish" and req.dish_id:
        channels = req.channels if req.channels else ["moments", "wecom_chat"]
        results = await _factory.generate_for_dish(
            x_tenant_id,
            req.dish_id,
            db,
            channels=channels,
        )
        return ok_response({"mode": "dish", "results": results})

    if req.mode == "holiday" and req.holiday:
        results = await _factory.generate_for_holiday(
            x_tenant_id,
            req.holiday,
            db,
        )
        return ok_response({"mode": "holiday", "results": results})

    if req.mode == "weekly_plan":
        results = await _factory.generate_weekly_plan(
            x_tenant_id,
            db,
            store_id=req.store_id,
        )
        return ok_response({"mode": "weekly_plan", "results": results})

    # Default: auto mode
    context = {
        "target_channel": req.target_channel,
        "dish_ids": req.dish_ids,
        "event_name": req.event_name,
        "holiday": req.holiday,
        "season": req.season,
        "brand_voice": req.brand_voice,
        "custom_prompt": req.custom_prompt,
    }
    result = await _factory.auto_generate(x_tenant_id, db, context)
    return ok_response({"mode": "auto", "result": result})


@router.post("/{content_id}/schedule")
async def schedule_content(
    content_id: str,
    req: ScheduleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """设置内容排期"""
    result = await _factory.schedule_content(
        x_tenant_id,
        content_id,
        req.scheduled_at,
        db,
    )
    if "error" in result:
        return error_response(result["error"])
    await db.commit()
    return ok_response(result)


@router.post("/{content_id}/publish")
async def publish_content(
    content_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """立即发布内容"""
    result = await _publisher.publish_single(x_tenant_id, content_id, db)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@router.get("/calendar-view")
async def calendar_view(
    year: int = Query(...),
    month: int = Query(...),
    store_id: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """日历视图（按日期分组，支持拖拽UI）"""
    await _set_tenant(db, x_tenant_id)

    conditions = [
        "tenant_id = :tid",
        "is_deleted = false",
        "EXTRACT(YEAR FROM COALESCE(scheduled_at, created_at)) = :year",
        "EXTRACT(MONTH FROM COALESCE(scheduled_at, created_at)) = :month",
    ]
    params: dict[str, Any] = {"tid": x_tenant_id, "year": year, "month": month}

    if store_id:
        conditions.append("(store_id = :store_id OR store_id IS NULL)")
        params["store_id"] = store_id

    where = " AND ".join(conditions)
    rows = await db.execute(
        text(f"""
            SELECT id, title, content_type, status,
                   COALESCE(scheduled_at, created_at) AS display_date,
                   ai_generated, store_id
            FROM content_calendar
            WHERE {where}
            ORDER BY display_date ASC
        """),
        params,
    )

    # 按日期分组
    by_date: dict[str, list[dict]] = {}
    for r in rows.mappings().all():
        date_key = r["display_date"].strftime("%Y-%m-%d")
        entry = {
            "id": str(r["id"]),
            "title": r["title"],
            "content_type": r["content_type"],
            "status": r["status"],
            "ai_generated": r["ai_generated"],
            "store_id": str(r["store_id"]) if r["store_id"] else None,
            "display_date": r["display_date"].isoformat(),
        }
        by_date.setdefault(date_key, []).append(entry)

    return ok_response({"year": year, "month": month, "dates": by_date})
