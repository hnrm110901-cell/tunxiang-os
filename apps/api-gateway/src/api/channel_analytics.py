"""
渠道分析 API — Phase P1
GET /channel-analytics/stats — 渠道统计
GET /channel-analytics/conversion — 转化率
GET /channel-analytics/cancellation — 退订率
POST /channel-analytics/record — 记录渠道
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from ..core.database import get_db
from ..core.dependencies import get_current_active_user
from ..models.user import User
from ..services.channel_analytics_service import channel_analytics_service

logger = structlog.get_logger()
router = APIRouter()


# ── Request / Response Models ──

class RecordChannelRequest(BaseModel):
    reservation_id: str
    store_id: str
    channel: str  # meituan/dianping/douyin/wechat/phone/walk_in/...
    external_order_id: Optional[str] = None
    commission_rate: Optional[float] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None


# ── Routes ──

@router.post("/channel-analytics/record", status_code=201)
async def record_channel(
    req: RecordChannelRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """记录预订渠道来源"""
    result = await channel_analytics_service.record_channel(
        session=session,
        reservation_id=req.reservation_id,
        store_id=req.store_id,
        channel=req.channel,
        external_order_id=req.external_order_id,
        commission_rate=req.commission_rate,
        utm_source=req.utm_source,
        utm_medium=req.utm_medium,
        utm_campaign=req.utm_campaign,
    )
    await session.commit()
    return result


@router.get("/channel-analytics/stats")
async def get_channel_stats(
    store_id: str = Query(..., description="门店ID"),
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """渠道来源统计（各渠道订单量/占比/佣金成本）"""
    return await channel_analytics_service.get_channel_stats(
        session=session,
        store_id=store_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/channel-analytics/conversion")
async def get_channel_conversion(
    store_id: str = Query(..., description="门店ID"),
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """各渠道转化率分析"""
    return await channel_analytics_service.get_channel_conversion(
        session=session,
        store_id=store_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/channel-analytics/cancellation")
async def get_cancellation_analysis(
    store_id: str = Query(..., description="门店ID"),
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """退订率分析"""
    return await channel_analytics_service.get_cancellation_analysis(
        session=session,
        store_id=store_id,
        start_date=start_date,
        end_date=end_date,
    )
