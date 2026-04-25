"""
AI评论回复管理 API

POST /api/v1/intel/reviews/{review_id}/generate-reply  — 生成AI回复
POST /api/v1/intel/reviews/{reply_id}/approve           — 审批回复
POST /api/v1/intel/reviews/{reply_id}/post               — 发布回复到平台
GET  /api/v1/intel/reviews/auto-replies                  — 回复列表（分页+筛选）
PUT  /api/v1/intel/reviews/brand-voice-config            — 更新品牌语调配置
GET  /api/v1/intel/reviews/brand-voice-config            — 获取品牌语调配置
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from services.review_replier import ReviewReplier
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/intel/reviews", tags=["review-replies"])

_replier = ReviewReplier()


# ─── 请求模型 ────────────────────────────────────────────────────────


class GenerateReplyRequest(BaseModel):
    brand_voice_config: dict[str, Any] | None = Field(
        default=None,
        description="可选的品牌语调配置覆盖 {tone, style, keywords}",
    )


class ApproveRequest(BaseModel):
    approved_by: str = Field(description="审批人UUID")


class BrandVoiceConfigRequest(BaseModel):
    tone: str = Field(default="warm", description="语调: warm/professional/casual")
    style: str = Field(default="亲切关怀", description="风格描述")
    keywords: list[str] = Field(default_factory=list, description="品牌关键词")


# ─── 路由 ─────────────────────────────────────────────────────────────


@router.post("/{review_id}/generate-reply")
async def generate_reply(
    review_id: str,
    body: GenerateReplyRequest | None = None,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """为指定评论生成AI回复"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _replier.generate_reply(
            tenant_id=uuid.UUID(x_tenant_id),
            review_id=uuid.UUID(review_id),
            db=db,
            brand_voice_config=body.brand_voice_config if body else None,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "NOT_FOUND"}}
    except SQLAlchemyError as exc:
        logger.error("review_reply.generate_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.post("/{reply_id}/approve")
async def approve_reply(
    reply_id: str,
    body: ApproveRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """审批通过一条AI回复"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _replier.approve_reply(
            tenant_id=uuid.UUID(x_tenant_id),
            reply_id=uuid.UUID(reply_id),
            approved_by=uuid.UUID(body.approved_by),
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "NOT_FOUND"}}
    except SQLAlchemyError as exc:
        logger.error("review_reply.approve_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.post("/{reply_id}/post")
async def post_reply(
    reply_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发布回复到平台"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _replier.post_reply(
            tenant_id=uuid.UUID(x_tenant_id),
            reply_id=uuid.UUID(reply_id),
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "INVALID_STATE"}}
    except RuntimeError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "POST_FAILED"}}
    except SQLAlchemyError as exc:
        logger.error("review_reply.post_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.get("/auto-replies")
async def list_auto_replies(
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    status: str | None = Query(None, description="状态筛选: draft/approved/posted/failed/expired"),
    platform: str | None = Query(None, description="平台筛选: dianping/meituan/douyin/google/xiaohongshu"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取AI回复列表（分页+筛选）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        filters = ""
        params: dict[str, Any] = {
            "tenant_id": x_tenant_id,
            "limit": size,
            "offset": (page - 1) * size,
        }
        if status:
            filters += " AND status = :status"
            params["status"] = status
        if platform:
            filters += " AND platform = :platform"
            params["platform"] = platform

        # 查询总数
        count_result = await db.execute(
            text(f"""
                SELECT COUNT(*) FROM review_auto_replies
                WHERE tenant_id = :tenant_id AND is_deleted = false {filters}
            """),
            params,
        )
        total = int(count_result.scalar() or 0)

        # 查询列表
        result = await db.execute(
            text(f"""
                SELECT id, review_id, platform, original_rating, original_text,
                       generated_reply, brand_voice_config, model_used, status,
                       approved_by, approved_at, posted_at, failure_reason,
                       created_at
                FROM review_auto_replies
                WHERE tenant_id = :tenant_id AND is_deleted = false {filters}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()
        items = []
        for row in rows:
            bv_config = row[6] if isinstance(row[6], dict) else (json.loads(row[6]) if row[6] else {})
            items.append(
                {
                    "id": str(row[0]),
                    "review_id": str(row[1]),
                    "platform": row[2],
                    "original_rating": float(row[3]) if row[3] is not None else None,
                    "original_text": row[4],
                    "generated_reply": row[5],
                    "brand_voice_config": bv_config,
                    "model_used": row[7],
                    "status": row[8],
                    "approved_by": str(row[9]) if row[9] else None,
                    "approved_at": row[10].isoformat() if row[10] else None,
                    "posted_at": row[11].isoformat() if row[11] else None,
                    "failure_reason": row[12],
                    "created_at": row[13].isoformat() if row[13] else None,
                }
            )

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
            },
        }
    except SQLAlchemyError as exc:
        logger.error("review_reply.list_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.put("/brand-voice-config")
async def update_brand_voice_config(
    body: BrandVoiceConfigRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新品牌语调配置"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        config_value = json.dumps(
            {"tone": body.tone, "style": body.style, "keywords": body.keywords},
            ensure_ascii=False,
        )

        # UPSERT品牌语调配置
        await db.execute(
            text("""
                INSERT INTO brand_strategy (id, tenant_id, config_key, config_value)
                VALUES (gen_random_uuid(), :tenant_id, 'brand_voice', :config_value::jsonb)
                ON CONFLICT (tenant_id, config_key)
                    WHERE is_deleted = false
                DO UPDATE SET
                    config_value = :config_value::jsonb,
                    updated_at = NOW()
            """),
            {"tenant_id": x_tenant_id, "config_value": config_value},
        )
        await db.commit()

        return {
            "ok": True,
            "data": {"tone": body.tone, "style": body.style, "keywords": body.keywords},
        }
    except SQLAlchemyError as exc:
        logger.error("review_reply.config_update_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.get("/brand-voice-config")
async def get_brand_voice_config(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前品牌语调配置"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        config = await _replier.get_brand_voice_config(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
        )
        return {"ok": True, "data": config}
    except SQLAlchemyError as exc:
        logger.error("review_reply.config_get_failed", error=str(exc))
        return {
            "ok": True,
            "data": {"tone": "warm", "style": "亲切关怀", "keywords": []},
        }
