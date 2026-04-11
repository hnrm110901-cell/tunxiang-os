"""ContentHub API — AI营销内容生成接口

提供基于 Claude API 的 AIGC 餐饮营销内容生成能力：
  POST /api/v1/brain/content/generate           — 生成全渠道活动内容包
  POST /api/v1/brain/content/review-response    — 生成点评回复
  POST /api/v1/brain/content/dish-story         — 生成菜品故事
  POST /api/v1/brain/content/xiaohongshu-note   — 生成小红书种草笔记
  GET  /api/v1/brain/content/cache-stats        — 缓存统计

所有接口需要 X-Tenant-ID 请求头。
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.content_hub import (
    BrandVoiceConfig,
    CampaignContentRequest,
    ContentHub,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/brain/content", tags=["content-hub"])

# ─────────────────────────────────────────────────────────────────────────────
# 依赖注入
# ─────────────────────────────────────────────────────────────────────────────


def _get_model_router() -> Any:
    """获取 ModelRouter 实例（从应用状态中取，测试可替换）"""
    from ..services.model_router_singleton import get_model_router  # lazy import
    return get_model_router()


def _get_content_hub() -> ContentHub:
    return ContentHub(model_router=_get_model_router())


async def _get_db() -> AsyncSession:  # type: ignore[misc]
    """数据库 Session 依赖（由 main.py 中的 SessionLocal 提供）"""
    from ..database import get_session
    async for session in get_session():
        yield session


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


# ─────────────────────────────────────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────────────────────────────────────


class GenerateContentBody(BaseModel):
    """生成活动内容包请求体"""
    model_config = ConfigDict(extra="ignore")

    campaign_type: str  # new_dish_launch/member_win_back/holiday_promo/daily_special/birthday_care/churn_recovery
    brand_voice: BrandVoiceConfig
    store_context: dict[str, Any]
    member_segment: Optional[dict[str, Any]] = None
    offer_detail: Optional[dict[str, Any]] = None
    target_channels: list[str] = ["sms", "wechat_oa_template", "wecom_chat"]
    ab_variants: int = 1


class ReviewResponseBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    review_text: str
    rating: int  # 1-5
    brand_voice: BrandVoiceConfig


class DishStoryBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dish_name: str
    dish_ingredients: list[str]
    brand_voice: BrandVoiceConfig


class XHSNoteBody(BaseModel):
    """生成小红书种草笔记请求体"""
    model_config = ConfigDict(extra="ignore")

    store_name: str
    dish_name: str
    brand_voice: dict = {}
    campaign_type: str = "store_visit"
    city: str = "长沙"
    target_audience: str = "年轻女性用户"


# ─────────────────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/generate")
async def generate_campaign_content(
    body: GenerateContentBody,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_db),
    hub: ContentHub = Depends(_get_content_hub),
) -> dict[str, Any]:
    """生成全渠道营销活动内容包

    一次调用生成所有目标渠道的文案（短信/公众号/企微话术/抖音/小红书等）。
    结果缓存24小时，相同品牌+活动类型不重复调用 Claude API。
    """
    try:
        request = CampaignContentRequest(
            campaign_type=body.campaign_type,
            brand_voice=body.brand_voice,
            store_context=body.store_context,
            member_segment=body.member_segment,
            offer_detail=body.offer_detail,
            target_channels=body.target_channels,
            ab_variants=body.ab_variants,
        )
        package = await hub.generate_campaign_content(request, tenant_id, db)
        return {"ok": True, "data": package.model_dump()}
    except ValueError as exc:
        logger.warning("content_generate_validation_error", tenant_id=tenant_id, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ConnectionError, TimeoutError) as exc:
        logger.error("content_generate_upstream_error", tenant_id=tenant_id, error=str(exc))
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable") from exc


@router.post("/review-response")
async def generate_review_response(
    body: ReviewResponseBody,
    tenant_id: str = Depends(_require_tenant),
    hub: ContentHub = Depends(_get_content_hub),
) -> dict[str, Any]:
    """为点评（美团/大众点评/抖音评论）生成商家回复文案

    根据评分和品牌调性生成得体的回复：
    - 好评（4-5星）：感谢 + 欢迎再来
    - 中评（3星）：诚恳致歉 + 承诺改进
    - 差评（1-2星）：主动沟通 + 解决方案
    """
    try:
        response_text = await hub.generate_review_response(
            review_text=body.review_text,
            rating=body.rating,
            brand_voice=body.brand_voice,
            tenant_id=tenant_id,
        )
        return {"ok": True, "data": {"response": response_text, "rating": body.rating}}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ConnectionError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable") from exc


@router.post("/dish-story")
async def generate_dish_story(
    body: DishStoryBody,
    tenant_id: str = Depends(_require_tenant),
    hub: ContentHub = Depends(_get_content_hub),
) -> dict[str, Any]:
    """为菜品生成品牌故事文案（用于菜单/小程序/朋友圈/小红书）"""
    try:
        story = await hub.generate_dish_story(
            dish_name=body.dish_name,
            dish_ingredients=body.dish_ingredients,
            brand_voice=body.brand_voice,
            tenant_id=tenant_id,
        )
        return {"ok": True, "data": {"story": story, "dish_name": body.dish_name}}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ConnectionError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable") from exc


@router.post("/xiaohongshu-note")
async def generate_xiaohongshu_note(
    body: XHSNoteBody,
    tenant_id: str = Depends(_require_tenant),
    hub: ContentHub = Depends(_get_content_hub),
) -> dict[str, Any]:
    """生成小红书种草笔记（标题+正文+标签+表情+封面建议）

    一次调用生成结构化小红书笔记，适合探店种草内容：
    - title: ≤20字吸引年轻女性用户的标题
    - body: 100-300字小红书风格正文（第一人称/口语化）
    - hashtags: 5-8个话题标签
    - emojis: 3-5个适合插入正文的表情建议
    - cover_concept: 一句话封面图构图建议
    - cta: 互动引导语
    """
    try:
        result = await hub.generate_xiaohongshu_note(
            tenant_id=tenant_id,
            store_name=body.store_name,
            dish_name=body.dish_name,
            brand_voice=body.brand_voice,
            campaign_type=body.campaign_type,
            city=body.city,
            target_audience=body.target_audience,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        logger.warning("xhs_note_validation_error", tenant_id=tenant_id, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ConnectionError, TimeoutError) as exc:
        logger.error("xhs_note_upstream_error", tenant_id=tenant_id, error=str(exc))
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable") from exc


@router.get("/cache-stats")
async def get_cache_stats(
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取 AIGC 内容缓存统计（节省 Token 成本分析）"""
    from sqlalchemy import text

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        row = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE expires_at > NOW()) AS active_count,
                    COUNT(*) FILTER (WHERE expires_at <= NOW()) AS expired_count,
                    SUM(tokens_used) FILTER (WHERE expires_at > NOW()) AS total_tokens_cached,
                    MIN(created_at) AS oldest_entry,
                    MAX(created_at) AS newest_entry
                FROM ai_content_cache
                WHERE tenant_id = current_setting('app.tenant_id')::uuid
                  AND NOT is_deleted
            """),
        )
        stats = row.mappings().one_or_none()
        return {
            "ok": True,
            "data": {
                "active_cache_entries": stats["active_count"] if stats else 0,
                "expired_entries": stats["expired_count"] if stats else 0,
                "total_tokens_saved": stats["total_tokens_cached"] if stats else 0,
                "oldest_entry": stats["oldest_entry"].isoformat() if stats and stats["oldest_entry"] else None,
                "newest_entry": stats["newest_entry"].isoformat() if stats and stats["newest_entry"] else None,
            },
        }
    except Exception as exc:  # noqa: BLE001 — top-level route handler
        logger.error("cache_stats_failed", tenant_id=tenant_id, error=str(exc), exc_info=True)
        return {"ok": False, "error": {"message": "Failed to fetch cache stats"}}
