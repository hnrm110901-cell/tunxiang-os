"""UGC裂变病毒引擎 API — 投稿 + AI审核 + 分享裂变

端点：
  POST  /api/v1/growth/ugc/submit              提交UGC（照片+文案）
  GET   /api/v1/growth/ugc/gallery/{store_id}   门店图墙（公开）
  POST  /api/v1/growth/ugc/{ugc_id}/review      触发AI质量审核
  POST  /api/v1/growth/ugc/{ugc_id}/approve     管理员审批通过
  POST  /api/v1/growth/ugc/{ugc_id}/reject      管理员拒绝（附原因）
  GET   /api/v1/growth/ugc/my                   我的投稿
  POST  /api/v1/growth/ugc/{ugc_id}/share       生成分享链接
  GET   /api/v1/growth/ugc/viral-stats          裂变统计仪表盘
"""

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator
from services.photo_reviewer import PhotoReviewer, PhotoReviewError
from services.ugc_service import UGCError, UGCService
from services.viral_tracker import ViralTracker, ViralTrackerError

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/ugc", tags=["ugc"])

_ugc_svc = UGCService()
_photo_reviewer = PhotoReviewer()
_viral_tracker = ViralTracker()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class SubmitUGCRequest(BaseModel):
    customer_id: uuid.UUID
    store_id: uuid.UUID
    media_urls: list[dict]
    caption: str = ""
    order_id: Optional[uuid.UUID] = None
    dish_ids: Optional[list[str]] = None

    @field_validator("media_urls")
    @classmethod
    def validate_media_urls(cls, v: list[dict]) -> list[dict]:
        if not v:
            raise ValueError("至少需要上传一张照片或视频")
        for item in v:
            if "url" not in item:
                raise ValueError("每个媒体项必须包含url字段")
            if item.get("type") not in ("photo", "video"):
                raise ValueError("媒体类型必须是 photo 或 video")
        return v


class RejectUGCRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("拒绝原因不能为空")
        return v.strip()


class ShareUGCRequest(BaseModel):
    customer_id: uuid.UUID
    channel: str = "wechat"
    campaign_id: Optional[uuid.UUID] = None
    parent_chain_id: Optional[uuid.UUID] = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        allowed = {"wechat", "moments", "wecom", "douyin", "xiaohongshu", "link"}
        if v not in allowed:
            raise ValueError(f"分享渠道必须是 {allowed} 之一")
        return v


# ---------------------------------------------------------------------------
# 端点实现
# ---------------------------------------------------------------------------


@router.post("/submit")
async def submit_ugc(
    req: SubmitUGCRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """顾客提交UGC（照片/视频+文案）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _ugc_svc.submit(
            tenant_id=tenant_id,
            customer_id=req.customer_id,
            store_id=req.store_id,
            media_urls=req.media_urls,
            caption=req.caption,
            db=db,
            order_id=req.order_id,
            dish_ids=req.dish_ids,
        )
        return ok_response(result)
    except UGCError as e:
        raise HTTPException(status_code=400, detail=error_response(e.message, e.code))


@router.get("/gallery/{store_id}")
async def get_gallery(
    store_id: uuid.UUID,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = 1,
    size: int = 20,
) -> dict:
    """获取门店图墙（已发布UGC）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    result = await _ugc_svc.get_gallery(
        tenant_id=tenant_id,
        store_id=store_id,
        db=db,
        page=page,
        size=size,
    )
    return ok_response(result)


@router.post("/{ugc_id}/review")
async def trigger_review(
    ugc_id: uuid.UUID,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """触发AI照片质量审核"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    # 先取出media_urls
    from sqlalchemy import text

    row = (
        await db.execute(
            text("""
            SELECT media_urls FROM ugc_submissions
            WHERE id = :ugc_id AND tenant_id = :tenant_id AND is_deleted = false
        """),
            {"ugc_id": str(ugc_id), "tenant_id": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=error_response("UGC不存在", "UGC_NOT_FOUND"))

    try:
        result = await _photo_reviewer.review_photo(
            tenant_id=tenant_id,
            ugc_id=ugc_id,
            media_urls=row.media_urls,
            db=db,
        )
        return ok_response(result)
    except PhotoReviewError as e:
        raise HTTPException(status_code=400, detail=error_response(e.message, e.code))


@router.post("/{ugc_id}/approve")
async def approve_ugc(
    ugc_id: uuid.UUID,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """管理员审批通过UGC"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _ugc_svc.approve(
            tenant_id=tenant_id,
            ugc_id=ugc_id,
            db=db,
        )
        return ok_response(result)
    except UGCError as e:
        raise HTTPException(status_code=404, detail=error_response(e.message, e.code))


@router.post("/{ugc_id}/reject")
async def reject_ugc(
    ugc_id: uuid.UUID,
    req: RejectUGCRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """管理员拒绝UGC"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _ugc_svc.reject(
            tenant_id=tenant_id,
            ugc_id=ugc_id,
            reason=req.reason,
            db=db,
        )
        return ok_response(result)
    except UGCError as e:
        raise HTTPException(status_code=404, detail=error_response(e.message, e.code))


@router.get("/my")
async def get_my_submissions(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    customer_id: uuid.UUID = None,
) -> dict:
    """获取我的UGC投稿历史"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    if not customer_id:
        raise HTTPException(status_code=400, detail=error_response("缺少customer_id参数", "MISSING_PARAM"))

    result = await _ugc_svc.get_my_submissions(
        tenant_id=tenant_id,
        customer_id=customer_id,
        db=db,
    )
    return ok_response(result)


@router.post("/{ugc_id}/share")
async def create_share_link(
    ugc_id: uuid.UUID,
    req: ShareUGCRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """生成UGC分享链接"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _viral_tracker.create_share_link(
            tenant_id=tenant_id,
            customer_id=req.customer_id,
            ugc_id=ugc_id,
            channel=req.channel,
            db=db,
            campaign_id=req.campaign_id,
            parent_chain_id=req.parent_chain_id,
        )
        return ok_response(result)
    except ViralTrackerError as e:
        raise HTTPException(status_code=400, detail=error_response(e.message, e.code))


@router.get("/viral-stats")
async def get_viral_stats(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    days: int = 30,
) -> dict:
    """裂变统计仪表盘"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    stats = await _viral_tracker.get_viral_stats(
        tenant_id=tenant_id,
        db=db,
        days=days,
    )

    # 附加排行榜
    top_sharers = await _viral_tracker.get_top_sharers(
        tenant_id=tenant_id,
        db=db,
        limit=20,
    )

    return ok_response(
        {
            "stats": stats,
            "top_sharers": top_sharers,
        }
    )
