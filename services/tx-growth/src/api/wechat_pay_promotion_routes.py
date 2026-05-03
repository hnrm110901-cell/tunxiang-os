"""微信支付营销 API — prefix /api/v1/growth/wechat-promotion

端点:
1. POST   /shake                    创建摇一摇优惠活动
2. POST   /merchant-card            配置商家名片
3. POST   /plan                     创建投放计划
4. GET    /activities               活动/名片/计划列表
5. GET    /activities/{id}          活动详情
6. PATCH  /activities/{id}/status   更新活动状态
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src.services.wechat_pay_promotion_service import get_promotion_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/wechat-promotion", tags=["growth-wechat-promotion"])


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreateShakeActivityRequest(BaseModel):
    """创建摇一摇优惠活动请求"""

    store_id: str = Field(..., description="门店 ID")
    activity_name: str = Field(..., description="活动名称")
    begin_time: str = Field(..., description="活动开始时间（ISO 8601）")
    end_time: str = Field(..., description="活动结束时间（ISO 8601）")
    award_amount_fen: int = Field(..., gt=0, description="优惠金额（分）")
    total_count: int = Field(..., gt=0, description="优惠总份数")
    operator_id: Optional[str] = Field(default=None, description="操作人 ID")


class CreateMerchantCardRequest(BaseModel):
    """配置商家名片请求"""

    store_id: str = Field(..., description="门店 ID")
    card_name: str = Field(..., description="名片名称")
    card_type: str = Field(..., description="名片类型")
    operator_id: Optional[str] = Field(default=None, description="操作人 ID")


class CreatePromotionPlanRequest(BaseModel):
    """创建投放计划请求"""

    store_id: str = Field(..., description="门店 ID")
    plan_name: str = Field(..., description="投放计划名称")
    plan_type: str = Field(..., description="投放计划类型")
    begin_time: str = Field(..., description="开始时间（ISO 8601）")
    end_time: str = Field(..., description="结束时间（ISO 8601）")
    operator_id: Optional[str] = Field(default=None, description="操作人 ID")


class UpdateActivityStatusRequest(BaseModel):
    """更新活动状态请求"""

    status: str = Field(..., description="状态: active/paused/ended/cancelled")
    operator_id: Optional[str] = Field(default=None, description="操作人 ID")


# ---------------------------------------------------------------------------
# 接口端点
# ---------------------------------------------------------------------------


@router.post("/shake")
async def create_shake_activity(
    req: CreateShakeActivityRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建摇一摇优惠活动

    在微信支付营销平台创建摇一摇优惠活动，
    用户支付后可在门店摇一摇领取优惠。
    """
    svc = get_promotion_service()
    try:
        result = await svc.create_shake_coupon_activity(
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            activity_name=req.activity_name,
            begin_time=req.begin_time,
            end_time=req.end_time,
            award_amount_fen=req.award_amount_fen,
            total_count=req.total_count,
            operator_id=req.operator_id,
        )
        logger.info(
            "wechat_promotion.shake_created",
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            activity_name=req.activity_name,
        )
        return ok_response(result)
    except ValueError as exc:
        logger.warning("wechat_promotion.shake_create_failed", error=str(exc))
        return error_response("PROMOTION_API_ERROR", f"创建摇一摇活动失败: {exc}")


@router.post("/merchant-card")
async def create_merchant_card(
    req: CreateMerchantCardRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """配置商家名片

    配置微信支付商家名片，展示在用户支付成功页面。
    """
    svc = get_promotion_service()
    try:
        result = await svc.create_merchant_card(
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            card_name=req.card_name,
            card_type=req.card_type,
            operator_id=req.operator_id,
        )
        logger.info(
            "wechat_promotion.merchant_card_created",
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            card_name=req.card_name,
        )
        return ok_response(result)
    except ValueError as exc:
        logger.warning("wechat_promotion.merchant_card_failed", error=str(exc))
        return error_response("PROMOTION_API_ERROR", f"配置商家名片失败: {exc}")


@router.post("/plan")
async def create_promotion_plan(
    req: CreatePromotionPlanRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建投放计划

    创建微信支付投放计划，用于精准营销触达。
    """
    svc = get_promotion_service()
    try:
        result = await svc.create_promotion_plan(
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            plan_name=req.plan_name,
            plan_type=req.plan_type,
            begin_time=req.begin_time,
            end_time=req.end_time,
            operator_id=req.operator_id,
        )
        logger.info(
            "wechat_promotion.plan_created",
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            plan_name=req.plan_name,
        )
        return ok_response(result)
    except ValueError as exc:
        logger.warning("wechat_promotion.plan_failed", error=str(exc))
        return error_response("PROMOTION_API_ERROR", f"创建投放计划失败: {exc}")


# ─── WP-2: 投放计划管理 ───


@router.get("/activities")
async def list_activities(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    activity_type: Optional[str] = Query(default=None, description="过滤类型: shake_coupon/merchant_card/promotion_plan"),
    status: Optional[str] = Query(default=None, description="过滤状态: active/paused/ended/cancelled"),
    limit: int = Query(default=50, ge=1, le=200, description="最大返回条数"),
) -> dict:
    """查询营销活动/名片/投放计划列表。"""
    svc = get_promotion_service()
    try:
        results = svc.list_activities(
            tenant_id=x_tenant_id,
            activity_type=activity_type,
            status=status,
            limit=limit,
        )
        return ok_response({"total": len(results), "items": results})
    except Exception as exc:
        logger.error("wechat_promotion.list_failed", error=str(exc))
        return error_response("PROMOTION_ERROR", str(exc))


@router.get("/activities/{activity_id}")
async def get_activity(
    activity_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取营销活动/名片/投放计划详情。"""
    svc = get_promotion_service()
    record = svc.get_activity(activity_id)
    if not record:
        raise HTTPException(status_code=404, detail="活动记录不存在")
    return ok_response(record)


@router.patch("/activities/{activity_id}/status")
async def update_activity_status(
    activity_id: str,
    req: UpdateActivityStatusRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新营销活动/名片/投放计划状态。"""
    valid_statuses = {"active", "paused", "ended", "cancelled"}
    if req.status not in valid_statuses:
        return error_response("INVALID_STATUS", f"状态值必须为 {valid_statuses}")

    svc = get_promotion_service()
    record = svc.update_activity_status(
        activity_id=activity_id,
        status=req.status,
        operator_id=req.operator_id,
    )
    if not record:
        raise HTTPException(status_code=404, detail="活动记录不存在")

    logger.info(
        "wechat_promotion.status_updated",
        activity_id=activity_id,
        status=req.status,
    )
    return ok_response(record)
