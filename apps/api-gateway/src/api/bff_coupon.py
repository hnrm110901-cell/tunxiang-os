"""BFF 发券 + ROI — P2"""

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID

from ..core.dependencies import get_db, get_current_user
from ..models.user import User
from ..services.coupon_distribution_service import coupon_distribution_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/bff/member-profile", tags=["BFF-发券"])


class DistributeCouponRequest(BaseModel):
    consumer_id: str
    coupon_source: str  # weishenghuo | service_voucher
    coupon_id: str
    coupon_name: Optional[str] = ""
    coupon_value_fen: Optional[int] = 0
    phone: Optional[str] = None


@router.post("/{store_id}/distribute-coupon", summary="发券")
async def distribute_coupon(
    store_id: str,
    req: DistributeCouponRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发放优惠券（微生活券透传 或 屯象服务券）"""
    distributed_by = current_user.id
    brand_id = current_user.brand_id or ""

    if req.coupon_source == "weishenghuo":
        if not req.phone:
            return {"success": False, "error": "微生活券需要手机号"}
        return await coupon_distribution_service.distribute_weishenghuo_coupon(
            db=db, consumer_id=UUID(req.consumer_id), store_id=store_id,
            brand_id=brand_id, coupon_id=req.coupon_id,
            coupon_name=req.coupon_name or "", coupon_value_fen=req.coupon_value_fen or 0,
            distributed_by=distributed_by, phone=req.phone,
        )
    elif req.coupon_source == "service_voucher":
        return await coupon_distribution_service.distribute_service_voucher(
            db=db, template_id=UUID(req.coupon_id),
            consumer_id=UUID(req.consumer_id), store_id=store_id,
            brand_id=brand_id, distributed_by=distributed_by,
        )
    else:
        return {"success": False, "error": f"未知券来源: {req.coupon_source}"}


@router.post("/{store_id}/confirm-service-voucher/{voucher_id}", summary="确认服务券核销")
async def confirm_service_voucher(
    store_id: str,
    voucher_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """员工确认服务券已送达"""
    confirmed_by = current_user.id
    return await coupon_distribution_service.confirm_service_voucher(
        db=db, voucher_id=UUID(voucher_id), confirmed_by=confirmed_by,
    )
