"""菜品搜索 + 热词 API — 真实 DB 接入

GET  /api/v1/menu/search/hot-keywords  — 热门搜索词列表（search_hot_keywords 表）
GET  /api/v1/menu/search               — 菜品全文搜索（dishes 表 ILIKE）
POST /api/v1/menu/search/record        — 记录搜索行为（upsert search_hot_keywords）

RLS 租户隔离：set_config('app.tenant_id', ...)
DB 不可用时 graceful 降级。
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/menu/search", tags=["menu-search"])


# ─── 请求模型 ───


class SearchRecordRequest(BaseModel):
    keyword: str = Field(..., max_length=50, description="搜索关键词")
    source: str = Field("miniapp", description="来源: miniapp / h5 / pos")


# ─── 辅助 ───


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 端点 ───


@router.get("/hot-keywords")
async def list_hot_keywords(
    limit: int = Query(10, ge=1, le=20, description="返回数量"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """热门搜索词列表（含运营推荐）"""
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("""
                SELECT keyword, search_count, is_promoted, display_order
                FROM search_hot_keywords
                WHERE tenant_id = :tid::uuid
                  AND is_active = true
                ORDER BY is_promoted DESC, display_order ASC, search_count DESC
                LIMIT :lim
            """),
            {"tid": x_tenant_id, "lim": limit},
        )
        rows = result.mappings().all()
        keywords = [
            {
                "keyword": r["keyword"],
                "search_count": r["search_count"],
                "is_promoted": r["is_promoted"],
                "display_order": r["display_order"],
            }
            for r in rows
        ]
        log.info("search.hot_keywords", tenant=x_tenant_id, limit=limit, count=len(keywords))
        return {
            "ok": True,
            "data": {"items": keywords, "total": len(keywords)},
        }
    except SQLAlchemyError as exc:
        log.error("search.hot_keywords_failed", error=str(exc), exc_info=True)
        return {"ok": True, "data": {"items": [], "total": 0, "_fallback": True}}


@router.get("")
async def search_dishes(
    q: str = Query(..., min_length=1, max_length=50, description="搜索关键词"),
    category: Optional[str] = Query(None, description="分类过滤（分类名称）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=50),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """菜品搜索（按菜名/描述 ILIKE 模糊匹配）"""
    try:
        await _set_rls(db, x_tenant_id)
        like_pat = f"%{q}%"
        params: dict = {
            "tid": x_tenant_id,
            "q": like_pat,
            "limit": size,
            "offset": (page - 1) * size,
        }
        cat_filter = ""
        if category:
            cat_filter = """
                AND EXISTS (
                    SELECT 1 FROM dish_categories dc
                    WHERE dc.id = d.category_id
                      AND dc.name ILIKE :cat_name
                )
            """
            params["cat_name"] = f"%{category}%"

        count_result = await db.execute(
            text(f"""
                SELECT count(*) FROM dishes d
                WHERE d.tenant_id = :tid::uuid
                  AND d.is_deleted = false
                  AND d.is_available = true
                  AND (d.dish_name ILIKE :q OR d.description ILIKE :q)
                {cat_filter}
            """),
            params,
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text(f"""
                SELECT d.id, d.dish_name, d.price_fen, d.image_url,
                       d.description, d.total_sales, d.rating,
                       dc.name AS category_name
                FROM dishes d
                LEFT JOIN dish_categories dc ON dc.id = d.category_id
                WHERE d.tenant_id = :tid::uuid
                  AND d.is_deleted = false
                  AND d.is_available = true
                  AND (d.dish_name ILIKE :q OR d.description ILIKE :q)
                {cat_filter}
                ORDER BY d.is_recommended DESC, d.total_sales DESC, d.dish_name
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()
        items = [
            {
                "dish_id": str(r["id"]),
                "dish_name": r["dish_name"],
                "category": r["category_name"],
                "price_fen": r["price_fen"],
                "image_url": r["image_url"],
                "description": r["description"],
                "total_sales": r["total_sales"],
                "rating": float(r["rating"]) if r["rating"] else None,
            }
            for r in rows
        ]
        log.info("search.dishes", tenant=x_tenant_id, query=q, category=category, total=total)
        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
                "query": q,
            },
        }
    except SQLAlchemyError as exc:
        log.error("search.dishes_failed", query=q, error=str(exc), exc_info=True)
        return {
            "ok": True,
            "data": {"items": [], "total": 0, "page": page, "size": size, "query": q, "_fallback": True},
        }


@router.post("/record")
async def record_search(
    body: SearchRecordRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """记录搜索行为（upsert 热词计数）"""
    try:
        await _set_rls(db, x_tenant_id)
        await db.execute(
            text("""
                INSERT INTO search_hot_keywords (id, tenant_id, keyword, search_count, is_active)
                VALUES (gen_random_uuid(), :tid::uuid, :kw, 1, true)
                ON CONFLICT ON CONSTRAINT uq_search_keyword_tenant
                DO UPDATE SET
                    search_count = search_hot_keywords.search_count + 1,
                    updated_at   = now()
            """),
            {"tid": x_tenant_id, "kw": body.keyword},
        )
        await db.commit()
        log.info("search.record", tenant=x_tenant_id, keyword=body.keyword, source=body.source)
        return {
            "ok": True,
            "data": {"keyword": body.keyword, "recorded": True},
        }
    except SQLAlchemyError as exc:
        log.error("search.record_failed", keyword=body.keyword, error=str(exc), exc_info=True)
        # 搜索记录失败不应影响用户体验，静默降级
        return {"ok": True, "data": {"keyword": body.keyword, "recorded": False, "_fallback": True}}
