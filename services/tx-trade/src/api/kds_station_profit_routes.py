"""档口毛利核算 API 路由"""
from datetime import date, timedelta
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.kds_station_profit import get_station_profit_summary

router = APIRouter(prefix="/api/v1/kds/station-profit", tags=["kds-station-profit"])


@router.get("")
async def api_station_profit(
    store_id: str,
    period: Literal["today", "week", "month"] = Query(default="today"),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询各档口毛利核算报表。

    - period: today/week/month（使用预设时间范围）
    - start_date / end_date: 自定义日期区间（优先级高于 period）

    毛利率颜色语义：
      ≥60% → healthy（绿色）
      40~60% → warning（黄色）
      <40% → danger（红色）
    """
    today = date.today()

    if start_date and end_date:
        s, e = start_date, end_date
    elif period == "today":
        s, e = today, today
    elif period == "week":
        s = today - timedelta(days=today.weekday())
        e = today
    else:  # month
        s = today.replace(day=1)
        e = today

    summary = await get_station_profit_summary(
        tenant_id=x_tenant_id,
        store_id=store_id,
        start_date=s,
        end_date=e,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            **summary,
            "period": period,
            "start_date": s.isoformat(),
            "end_date": e.isoformat(),
        },
    }
