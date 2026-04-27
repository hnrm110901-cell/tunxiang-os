"""
GEO搜索优化 API

POST /api/v1/intel/geo-seo/profile/{store_id}  — 生成/更新门店结构化数据
GET  /api/v1/intel/geo-seo/profiles             — 列出所有门店GEO档案
POST /api/v1/intel/geo-seo/citation-check       — 触发AI引用检测
GET  /api/v1/intel/geo-seo/citations            — 引用监测结果列表（分页）
GET  /api/v1/intel/geo-seo/dashboard            — GEO SEO仪表盘
POST /api/v1/intel/geo-seo/optimize/{store_id}  — 获取门店优化建议
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from services.geo_seo_service import GeoSEOService
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/intel/geo-seo", tags=["geo-seo"])

_geo_svc = GeoSEOService()


# ─── 请求模型 ────────────────────────────────────────────────────────


class CitationCheckRequest(BaseModel):
    query: str = Field(description="查询语句，例如：长沙最好的海鲜餐厅")
    platform: str = Field(
        default="chatgpt",
        description="平台: chatgpt/perplexity/google_ai/baidu_ai/xiaohongshu",
    )


# ─── 路由 ─────────────────────────────────────────────────────────────


@router.post("/profile/{store_id}")
async def generate_profile(
    store_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成/更新门店结构化数据（Schema.org Restaurant JSON-LD）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _geo_svc.generate_structured_data(
            tenant_id=uuid.UUID(x_tenant_id),
            store_id=uuid.UUID(store_id),
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "INVALID_INPUT"}}
    except SQLAlchemyError as exc:
        logger.error("geo_seo.generate_profile_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.get("/profiles")
async def list_profiles(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出所有门店GEO档案（按seo_score降序，分页）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        offset = (page - 1) * size

        count_row = await db.execute(
            text("""
                SELECT COUNT(DISTINCT store_id) AS total
                FROM geo_brand_profiles
                WHERE tenant_id = :tid AND is_deleted = FALSE
            """),
            {"tid": x_tenant_id},
        )
        total = count_row.scalar() or 0

        rows = await db.execute(
            text("""
                SELECT store_id, store_name, platform, seo_score,
                       address, phone, cuisine_type, citation_found,
                       updated_at
                FROM geo_brand_profiles
                WHERE tenant_id = :tid AND is_deleted = FALSE
                ORDER BY seo_score DESC, updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"tid": x_tenant_id, "limit": size, "offset": offset},
        )
        items = [
            {
                "store_id": str(r["store_id"]),
                "store_name": r["store_name"],
                "platform": r["platform"],
                "seo_score": r["seo_score"],
                "address": r["address"],
                "phone": r["phone"],
                "cuisine_type": r["cuisine_type"],
                "citation_found": r["citation_found"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows.mappings().all()
        ]
        return {"ok": True, "data": {"items": items, "total": total}}
    except SQLAlchemyError as exc:
        logger.error("geo_seo.list_profiles_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.post("/citation-check")
async def check_citation(
    body: CitationCheckRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """触发AI引用检测"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _geo_svc.check_ai_citation(
            tenant_id=uuid.UUID(x_tenant_id),
            query=body.query,
            platform=body.platform,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "INVALID_INPUT"}}
    except SQLAlchemyError as exc:
        logger.error("geo_seo.citation_check_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.get("/citations")
async def list_citations(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    platform: str | None = Query(None, description="按平台筛选"),
    mention_only: bool = Query(False, description="只显示被引用的"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """引用监测结果列表（分页）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        offset = (page - 1) * size

        where_clauses = ["tenant_id = :tid", "is_deleted = FALSE"]
        params: dict[str, Any] = {"tid": x_tenant_id, "limit": size, "offset": offset}

        if platform:
            where_clauses.append("platform = :platform")
            params["platform"] = platform
        if mention_only:
            where_clauses.append("mention_found = TRUE")

        where_sql = " AND ".join(where_clauses)

        count_row = await db.execute(
            text(f"SELECT COUNT(*) FROM ai_citation_monitors WHERE {where_sql}"),
            params,
        )
        total = count_row.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT id, query, platform, mention_found, mention_text,
                       mention_position, competitor_mentions, sentiment,
                       checked_at, check_round
                FROM ai_citation_monitors
                WHERE {where_sql}
                ORDER BY checked_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [
            {
                "id": str(r["id"]),
                "query": r["query"],
                "platform": r["platform"],
                "mention_found": r["mention_found"],
                "mention_text": r["mention_text"],
                "mention_position": r["mention_position"],
                "competitor_mentions": r["competitor_mentions"],
                "sentiment": r["sentiment"],
                "checked_at": r["checked_at"].isoformat() if r["checked_at"] else None,
                "check_round": r["check_round"],
            }
            for r in rows.mappings().all()
        ]
        return {"ok": True, "data": {"items": items, "total": total}}
    except SQLAlchemyError as exc:
        logger.error("geo_seo.list_citations_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.get("/dashboard")
async def get_dashboard(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GEO SEO仪表盘"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _geo_svc.get_seo_dashboard(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "INVALID_INPUT"}}
    except SQLAlchemyError as exc:
        logger.error("geo_seo.dashboard_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.post("/optimize/{store_id}")
async def optimize_store(
    store_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取门店SEO优化建议"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _geo_svc.optimize_content_suggestions(
            tenant_id=uuid.UUID(x_tenant_id),
            store_id=uuid.UUID(store_id),
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "INVALID_INPUT"}}
    except SQLAlchemyError as exc:
        logger.error("geo_seo.optimize_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}
